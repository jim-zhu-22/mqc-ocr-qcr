import base64
import json
import time
import httpx
from .store import scrub


class ModelError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1])
    return json.loads(text)


class ModelClient:
    def __init__(self, endpoint, audit=None, secrets=(), transport=None):
        self.endpoint = endpoint
        self.audit = audit or (lambda x: None)
        self.secrets = (*secrets, endpoint.api_key.get_secret_value())
        self.transport = transport

    def call(self, prompt, image=None, tag="model"):
        cfg = self.endpoint
        if not cfg.base_url or not cfg.model:
            raise ModelError("CONFIG_REQUIRED", "请填写API地址与模型名称；需要认证的服务还需密钥。")
        url = cfg.base_url if cfg.base_url.endswith("/chat/completions") else cfg.base_url + "/chat/completions"
        content = prompt
        if image:
            content = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(image).decode()}}]
        payload = {"model": cfg.model, "messages": [{"role": "user", "content": content}], "temperature": 0, "max_tokens": cfg.max_tokens, "stream": False}
        headers = {"Content-Type": "application/json"}
        if cfg.api_key.get_secret_value():
            headers["Authorization"] = "Bearer " + cfg.api_key.get_secret_value()
        for attempt in range(cfg.retries + 1):
            started = time.monotonic()
            entry = {"tag": tag, "attempt": attempt + 1, "model": cfg.model, "prompt": prompt, "image_attached": bool(image)}
            retry = False
            try:
                with httpx.Client(timeout=cfg.timeout_seconds, follow_redirects=False, trust_env=False, transport=self.transport) as client:
                    response = client.post(url, headers=headers, json=payload)
                entry.update(http_status=response.status_code, raw_response=response.text)
                if response.status_code >= 400 or 300 <= response.status_code < 400:
                    retry = response.status_code in (408, 429, 500, 502, 503, 504)
                    code = "AUTH_FAILED" if response.status_code in (401, 403) else "HTTP_ERROR"
                    message = f"模型服务HTTP {response.status_code}；请检查地址、认证、模型及服务配额。"
                    raise ModelError(code, message)
                data = response.json()
                choice = data["choices"][0]
                if choice.get("finish_reason") == "length":
                    raise ModelError("TRUNCATED", "模型输出达到token上限，请提高max_tokens或使用更大上下文模型。")
                text = choice["message"]["content"]
                if not isinstance(text, str) or not text.strip():
                    raise ModelError("EMPTY_OUTPUT", "模型未返回可用文本。")
                entry.update(status="completed", elapsed_seconds=round(time.monotonic() - started, 3))
                self.audit(scrub(entry, self.secrets))
                return scrub(text, self.secrets)
            except httpx.TimeoutException:
                retry = True
                error = ModelError("TIMEOUT", "模型请求超时；可提高超时并检查服务负载。")
            except httpx.RequestError:
                retry = True
                error = ModelError("CONNECTION_FAILED", "无法连接模型服务；检查网络、证书和API地址。")
            except ModelError as exc:
                error = exc
            except (ValueError, KeyError, IndexError, TypeError):
                error = ModelError("RESPONSE_FORMAT", "响应不符合Chat Completions格式；原始响应已保留。")
            entry.update(status="failed", error={"code": error.code, "message": str(error)}, elapsed_seconds=round(time.monotonic() - started, 3))
            self.audit(scrub(entry, self.secrets))
            if not retry or attempt >= cfg.retries:
                raise error
            time.sleep(min(2 ** attempt, 8))
