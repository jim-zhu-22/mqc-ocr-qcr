import copy
import hashlib
import io
import json
from pathlib import Path
import pymupdf as fitz
from PIL import Image
from .client import ModelClient, parse_json
from .rules import PROMPTS, compile_rules, normalize_rules
from .sections import split_sections
from .scoring import score_records
from .contracts import ScoreInput

SAMPLES = Path(__file__).parent / "samples"


def read_sample(name):
    return json.loads((SAMPLES / name).read_text(encoding="utf-8-sig"))


def sample_input():
    materials = read_sample("materials.json")
    catalog = read_sample("catalog.json")
    refs = {r["reference_id"]: r for r in catalog["references"]}
    links = {r["sample_id"]: r["reference_id"] for r in read_sample("reference_links.json")["links"]}
    for m in materials:
        ref = refs.get(links[m["sample_id"]])
        if ref:
            m["_selection_catalog"] = catalog
            m["source_evidence"] = [{"source": "SYNTHETIC_CATALOG", "fields": {"cn_description": f"{ref['cn_name']} [{ref['model']}]", "cn_po_text": f"{ref['cn_name']} [{ref['model']}]", "en_description": f"{ref['en_name']} [{ref['model']}]", "en_po_text": f"{ref['en_name']} [{ref['model']}]", "manufacturer": "Manufacturer A"}}]
    return {"materials": materials, "catalog": catalog, "dimension_weights": {d: 1 for d in ("necessity", "completeness", "accuracy", "uniqueness")}, "ml": {}}


def render_pages(content, suffix):
    if suffix.lower() == ".pdf":
        with fitz.open(stream=content, filetype="pdf") as doc:
            if doc.needs_pass:
                raise ValueError("PDF已加密，请提供可打开的文件")
            if not 1 <= len(doc) <= 100:
                raise ValueError("PDF须包含1至100页")
            for number, page in enumerate(doc, 1):
                scale = min(2, 2400 / max(page.rect.width, page.rect.height))
                yield number, page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes("png")
    else:
        with Image.open(io.BytesIO(content)) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError("图像超过4000万像素限制")
            image = image.convert("RGB")
            image.thumbnail((2400, 2400))
            stream = io.BytesIO()
            image.save(stream, format="PNG")
            yield 1, stream.getvalue()


class Pipeline:
    def __init__(self, store, run_id, config, transport=None):
        self.store, self.run_id, self.config = store, run_id, config
        self.secrets = (config.ocr.api_key.get_secret_value(), config.text.api_key.get_secret_value())
        self.calls = []
        self.transport = transport
        self.call_name = "model_calls"

    def audit(self, call):
        self.calls.append(call)
        self.store.stage(self.run_id, self.call_name, {"calls": self.calls}, secrets=self.secrets)

    def client(self, kind):
        return ModelClient(getattr(self.config, kind), self.audit, self.secrets, self.transport)

    def write(self, name, data, **kwargs):
        self.store.stage(self.run_id, name, data, secrets=self.secrets, **kwargs)

    def run(self, content, suffix, mode):
        store, rid = self.store, self.run_id
        stage = "ocr"
        try:
            store.update(rid, status="running", stage=stage)
            pages = []
            self.write("ocr", {"pages": pages}, status="running")
            if mode == "replay":
                content = (SAMPLES / "control_sheet.pdf").read_bytes()
                suffix = ".pdf"
                pages = read_sample("ocr.json")["pages"]
                self.write("replay_provenance", {"ocr_origin": "既有Codex视觉识别文本重放；不是Qwen或本次OCR API调用", "rules_origin": "用户认可的照片排除规则及确定性合成参考库适配", "models_executed": False})
                for number, png in render_pages(content, suffix):
                    store.path(rid, f"page-{number}.png").write_bytes(png)
            else:
                prompt = (PROMPTS / "ocr_original.txt").read_text(encoding="utf-8")
                for number, png in render_pages(content, suffix):
                    store.path(rid, f"page-{number}.png").write_bytes(png)
                    raw = self.client("ocr").call(prompt, png, tag=f"ocr:page:{number}")
                    page = {"page_num": number, "text_content": raw, "raw_output": raw, "image_sha256": hashlib.sha256(png).hexdigest(), "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "status": "completed"}
                    pages.append(page)
                    self.write("ocr", {"pages": pages}, status="running")
            self.write("ocr", {"pages": pages, "mode": mode})
            stage = "sections"
            store.update(rid, stage=stage)
            sections = split_sections(pages)
            self.write("sections", sections)
            stage = "rules"
            store.update(rid, stage=stage)
            if mode == "replay":
                rules, dsl = self.replay_rules(sections["sections"])
                self.write("rules-v1", {"rules": rules, "excluded": [{"reason": "照片识别不参与四性评分"}]})
                ir = [{"source_rule_id": r["id"], "semantic_items": r["checks"], "source_pages": r["source_pages"]} for r in rules]
                self.write("ir-v1", {"ir": ir})
                self.write("dsl-v1", {"dsl": dsl, "errors": []})
                store.update(rid, revision=1, compiled_revision=1)
            else:
                raw = self.client("text").call((PROMPTS / "extract_v1.txt").read_text(encoding="utf-8") + json.dumps(sections, ensure_ascii=False), tag="extract")
                self.write("rules-raw", {"raw_output": raw})
                rules, excluded = normalize_rules(parse_json(raw), sections["sections"])
                self.write("rules-v1", {"rules": rules, "excluded": excluded})
                store.update(rid, revision=1)
                stage = "compile"
                self.compile(1)
            store.update(rid, status="completed", stage="ready_to_score")
        except Exception as exc:
            self.fail(stage, exc)

    def fail(self, stage, exc):
        # Do not persist arbitrary exception strings (may contain input secrets/URLs).
        message = str(exc) if isinstance(exc, ValueError) else "阶段执行失败，请查看已保留的原始响应和配置"
        from .store import scrub
        error = scrub({"code": getattr(exc, "code", "STAGE_FAILED"), "message": message}, self.secrets)
        self.write(stage + "-error", {"partial_artifacts_preserved": True}, status="failed", error=error)
        self.store.update(self.run_id, status="failed", stage=stage, error=error)

    def compile(self, revision):
        self.call_name = f"compile-calls-v{revision}"
        self.calls = []
        store, rid = self.store, self.run_id
        store.update(rid, status="running", stage="compile")
        rules = store.read(rid, f"rules-v{revision}.json")["data"]["rules"]
        sections = store.read(rid, "sections.json")["data"]["sections"]
        document_id = store.read(rid, "run.json")["document_id"]
        def progress(ir, dsl, errors):
            self.write(f"ir-v{revision}", {"ir": ir}, status="running")
            self.write(f"dsl-v{revision}", {"dsl": dsl, "errors": errors}, status="running")
        ir, dsl, errors = compile_rules(rules, sections, document_id, self.client("text"), progress)
        status = "partial" if errors or any(d["execution_status"] == "pending_review" for d in dsl) else "completed"
        self.write(f"ir-v{revision}", {"ir": ir}, status=status)
        self.write(f"dsl-v{revision}", {"dsl": dsl, "errors": errors}, status=status)
        store.update(rid, status="completed", stage="ready_to_score", compiled_revision=revision, compilation_status=status)

    def replay_rules(self, sections):
        legacy = read_sample("legacy_dsl.json")
        refs = {1: ["3"], 2: ["4.1", "4.2", "4.3"], 4: ["5"], 5: ["5"], 6: ["5"], 7: ["5"], 8: ["5"], 9: ["5"], 10: ["4.2"]}
        smap = {s["section"]: s for s in sections}
        rules, dsl = {}, []
        for item in legacy:
            sid = item["source_rule_id"]
            rule_key = f"R{sid:04d}"
            pages = sorted({p for s in refs[sid] for p in smap[s]["pages"]})
            checks = rules.setdefault(rule_key, {"id": rule_key, "quality_type": item["quality_type"], "rule_title": item["rule_title"], "rule_text": item["source_text"], "material_entity": item["material_entity"], "condition_text": item["condition_text"], "source_sections": refs[sid], "source_pages": pages, "weight": item["rule_weight"], "enabled": True, "source_type": "replay", "checks": []})["checks"]
            check = {k: copy.deepcopy(item[k]) for k in ("field_name", "operator", "expected_value")}
            # Editable replay checks use the portable identity operators after a revision.
            if item.get("offline_handler"):
                check.update(operator="identification_complete" if sid == 2 else "identity_unique", expected_value={"model_fields": ["model", "spec_model"], "parameter_fields": ["dial_size", "mounting_type", "process_connection_size", "accuracy_class", "oil_filled", "measuring_range"]})
            checks.append(check)
            dsl.append({**item, "dsl_id": f"{rule_key}.{len(checks)}", "rule_key": rule_key, "source_sections": refs[sid], "source_pages": pages, "execution_status": "ready"})
        return list(rules.values()), dsl

    def score(self, payload, score_id, revision):
        self.call_name = f"score-calls-{score_id}"
        self.calls = []
        store, rid = self.store, self.run_id
        stage = f"scores-{score_id}"
        try:
            manifest = store.read(rid, "run.json")
            dsl = store.read(rid, f"dsl-v{revision}.json")["data"]["dsl"]
            for cfg in payload.ml.values():
                key = (cfg.get("endpoint") or {}).get("api_key")
                if key:
                    self.secrets += (key,)
            self.write(f"score-input-{score_id}", {"rule_revision": revision, "input": payload.model_dump()})
            def progress(results):
                self.write(stage, {"rule_revision": revision, "results": results}, status="running")
            results = score_records(dsl, payload, self.client("text") if self.config.text.base_url else None, replay=manifest["mode"] == "replay" and revision == 1, on_progress=progress)
            self.write(stage, {"rule_revision": revision, "results": results, "summary": {"records": len(results), "rule_checks": sum(len(r["details"]) for r in results), "numeric_scores": len(results) * 5, "ml_enabled": [k for k, v in payload.ml.items() if v.get("enabled")]}})
            manifest = store.read(rid, "run.json")
            store.update(rid, status="completed", stage="scored", scores=manifest["scores"] + [{"id": score_id, "revision": revision, "artifact": stage + ".json"}])
        except Exception as exc:
            self.fail(stage, exc)
