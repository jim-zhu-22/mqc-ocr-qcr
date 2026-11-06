import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def scrub(value, secrets=()):
    """Redact configured secrets in arbitrary model responses and nested records."""
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if re.search(r"api.?key|authorization|password|secret|access.?token", str(k), re.I) else scrub(v, secrets)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(x, secrets) for x in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)Bearer\s+[^\s\"']+", "Bearer [REDACTED]", value)
    return value


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def directory(self, run_id):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("无效任务ID")
        return self.root / run_id

    def path(self, run_id, name):
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", name) or name.startswith("."):
            raise ValueError("无效产物名称")
        return self.directory(run_id) / name

    def save(self, run_id, name, payload, secrets=()):
        path = self.path(run_id, name)
        with self.lock:
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_text(json.dumps(scrub(payload, secrets), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            temp.replace(path)

    def read(self, run_id, name):
        return json.loads(self.path(run_id, name).read_text(encoding="utf-8"))

    def create(self, mode, document_id, config):
        run_id = uuid4().hex
        self.directory(run_id).mkdir()
        self.save(run_id, "run.json", {"schema_version": "1", "id": run_id, "mode": mode, "document_id": document_id, "created_at": now(), "status": "queued", "stage": "input", "revision": 0, "scores": [], "configuration": config})
        return run_id

    def update(self, run_id, **changes):
        with self.lock:
            manifest = self.read(run_id, "run.json")
            manifest.update(changes, updated_at=now())
            self.save(run_id, "run.json", manifest)

    def stage(self, run_id, name, data, status="completed", error=None, secrets=()):
        self.save(run_id, name + ".json", {"schema_version": "1", "run_id": run_id, "stage": name, "status": status, "created_at": now(), "data": data, "error": error}, secrets)

    def list_runs(self):
        results = []
        for path in self.root.glob("*/run.json"):
            try:
                results.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(results, key=lambda x: x["created_at"], reverse=True)

    def recover(self):
        for run in self.list_runs():
            if run["status"] in ("queued", "running"):
                self.update(run["id"], status="interrupted", error={"code": "PROCESS_RESTART", "message": "进程重启中断任务；已完成产物保留，请新建运行或重新编译/评分。"})
