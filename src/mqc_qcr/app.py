import copy
import hashlib
import io
import json
import os
import re
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from .contracts import ModelConfig, Rule, ScoreInput
from .pipeline import Pipeline, SAMPLES, sample_input
from .rules import normalize_checks, photo_rule
from .store import Store, scrub


def create_app(data_dir=None):
    store = Store(data_dir or os.getenv("MQC_DATA_DIR", "runtime"))
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mqc")
    lock = threading.RLock()
    config = ModelConfig()

    @asynccontextmanager
    async def lifespan(app):
        store.recover()
        yield
        executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="MQC-OCR-QCR", version="0.0.0.dev0", lifespan=lifespan)
    app.state.store = store
    app.state.executor = executor

    @app.middleware("http")
    async def local_only(request, call_next):
        host = request.url.hostname
        origin = request.headers.get("origin")
        if host not in ("127.0.0.1", "localhost", "testserver") or (origin and origin != str(request.base_url).rstrip("/")):
            return JSONResponse({"error": "仅支持同源本机访问"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Pydantic errors include raw input by default; never echo credentials.
        return JSONResponse({"error": "请求字段或类型无效", "fields": [{"loc": list(e["loc"]), "type": e["type"]} for e in exc.errors()]}, status_code=422)

    @app.exception_handler(ValueError)
    async def invalid_value(request, exc):
        return JSONResponse({"error": "输入内容不符合契约，请检查JSON、来源章节、字段与权重"}, status_code=400)

    @app.exception_handler(FileNotFoundError)
    async def missing(request, exc):
        return JSONResponse({"error": "任务或产物不存在"}, status_code=404)

    def manifest(run_id):
        return store.read(run_id, "run.json")

    def idle(run_id):
        result = manifest(run_id)
        if result["status"] in ("queued", "running"):
            raise HTTPException(409, "任务正在执行，请等待完成")
        return result

    def pipeline(run_id):
        with lock:
            snapshot = config.model_copy(deep=True)
        return Pipeline(store, run_id, snapshot)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.0.0.dev0", "formal_release": False}

    @app.get("/api/config")
    def get_config():
        with lock:
            return {"ocr": config.ocr.public(), "text": config.text.public()}

    @app.put("/api/config")
    def set_config(value: ModelConfig):
        nonlocal config
        with lock:
            config = value.model_copy(deep=True)
        return get_config()

    @app.post("/api/config/check/{kind}")
    def check_config(kind: str):
        if kind not in ("ocr", "text"):
            raise HTTPException(404)
        from .client import ModelClient, ModelError
        from PIL import Image, ImageDraw
        with lock:
            endpoint = getattr(config, kind).model_copy(deep=True)
        png = None
        if kind == "ocr":
            image = Image.new("RGB", (280, 100), "white")
            ImageDraw.Draw(image).text((15, 35), "MQC CONNECTION TEST 123", fill="black")
            buffer = io.BytesIO()
            image.save(buffer, "PNG")
            png = buffer.getvalue()
        try:
            result = ModelClient(endpoint).call("Read the text in this image." if png else "Reply OK.", png, tag="connection-check")
            return {"status": "connected", "kind": kind, "response": result[:300], "scope": "一次真实请求验证连接及响应；不证明OCR或规则准确率"}
        except ModelError as exc:
            return JSONResponse({"status": "failed", "code": exc.code, "message": str(exc)}, status_code=502)

    @app.get("/api/samples/input")
    def sample():
        return sample_input()

    @app.get("/api/samples/document")
    def sample_document():
        return FileResponse(SAMPLES / "control_sheet.pdf", filename="control_sheet.pdf")

    @app.post("/api/runs")
    async def create_run(mode: str = Form("live"), document_id: str = Form(""), file: UploadFile | None = File(None)):
        if mode not in ("live", "replay"):
            raise HTTPException(400, "模式须为live或replay")
        if not document_id.strip() or len(document_id) > 120:
            raise HTTPException(400, "请填写控制单编号（最多120字符）")
        content, suffix = b"", ".pdf"
        if mode == "live":
            if not file:
                raise HTTPException(400, "请选择PDF或图像")
            suffix = Path(file.filename or "").suffix.lower()
            if suffix not in (".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"):
                raise HTTPException(400, "仅支持PDF/PNG/JPEG/WebP/TIFF/BMP")
            content = await file.read(30 * 1024 * 1024 + 1)
            await file.close()
            if not content or len(content) > 30 * 1024 * 1024:
                raise HTTPException(400, "文件须非空且不超过30MB")
        with lock:
            snapshot = config.model_copy(deep=True)
        rid = store.create(mode, document_id.strip(), {"ocr": snapshot.ocr.public(), "text": snapshot.text.public()})
        store.stage(rid, "input", {"document_id": document_id.strip(), "mode": mode, "suffix": suffix, "sha256": hashlib.sha256(content).hexdigest() if content else None})
        if content:
            store.path(rid, "input" + suffix).write_bytes(content)
        executor.submit(Pipeline(store, rid, snapshot).run, content, suffix, mode)
        return {"run_id": rid}

    @app.get("/api/runs")
    def list_runs():
        return {"runs": store.list_runs()}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        result = manifest(run_id)
        result["artifacts"] = sorted(p.name for p in store.directory(run_id).glob("*.json"))
        result["pages"] = sorted(p.name for p in store.directory(run_id).glob("page-*.png"))
        return result

    @app.get("/api/runs/{run_id}/artifacts/{name}")
    def artifact(run_id: str, name: str, download: bool = False):
        manifest(run_id)
        if not name.endswith(".json"):
            raise HTTPException(400)
        data = store.read(run_id, name)
        if download:
            return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{name}"'})
        return data

    @app.get("/api/runs/{run_id}/pages/{number}")
    def page(run_id: str, number: int):
        manifest(run_id)
        if not 1 <= number <= 100:
            raise HTTPException(404)
        return FileResponse(store.path(run_id, f"page-{number}.png"), media_type="image/png")

    @app.get("/api/runs/{run_id}/export")
    def export(run_id: str):
        idle(run_id)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(store.directory(run_id).glob("*.json")):
                archive.writestr(path.name, path.read_bytes())
        return Response(stream.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{run_id}.zip"'})

    @app.put("/api/runs/{run_id}/rules")
    def save_rules(run_id: str, rules: list[Rule]):
        with lock:
            run = idle(run_id)
            sections = store.read(run_id, "sections.json")["data"]["sections"]
            smap = {s["section"]: s for s in sections}
            values, ids = [], set()
            for rule in rules:
                value = rule.model_dump()
                if rule.id in ids or any(s not in smap for s in rule.source_sections):
                    raise HTTPException(400, "规则ID重复或来源章节不存在")
                if photo_rule(value) and rule.enabled:
                    raise HTTPException(400, "照片规则不可启用")
                ids.add(rule.id)
                value["source_pages"] = sorted({p for s in rule.source_sections for p in smap[s]["pages"]})
                value["source_type"] = "manual"
                if value["checks"]:
                    value["checks"] = normalize_checks(value["checks"], rule.quality_type)
                values.append(value)
            revision = run["revision"] + 1
            store.stage(run_id, f"rules-v{revision}", {"rules": values, "parent_revision": run["revision"]})
            store.update(run_id, revision=revision, status="running", stage="compile")
            worker = pipeline(run_id)
            def work():
                try:
                    worker.compile(revision)
                except Exception as exc:
                    worker.fail("compile", exc)
            executor.submit(work)
            return {"revision": revision, "message": "规则已保存并自动更新DSL；已有评分保持不变，请手动复评"}

    @app.post("/api/runs/{run_id}/score")
    def score(run_id: str, payload: ScoreInput):
        with lock:
            run = idle(run_id)
            revision = run["revision"]
            if revision == 0 or run.get("compiled_revision") != revision:
                raise HTTPException(409, "当前规则版本尚未编译完成")
            score_id = uuid4().hex[:16]
            store.update(run_id, status="running", stage="scoring")
            executor.submit(pipeline(run_id).score, payload, score_id, revision)
            return {"score_id": score_id, "rule_revision": revision}

    @app.get("/api/schemas")
    def schemas():
        return {"model_config": ModelConfig.model_json_schema(), "rule": Rule.model_json_schema(), "score_input": ScoreInput.model_json_schema(), "stage_envelope": {"schema_version": "1", "run_id": "uuid-hex", "stage": "artifact-stage", "status": "running|completed|partial|failed", "created_at": "ISO8601-UTC", "data": {}, "error": None}}

    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    return app


app = create_app()
