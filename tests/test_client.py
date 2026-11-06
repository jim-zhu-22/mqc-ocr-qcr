import json
import httpx
import pytest
from mqc_qcr.client import ModelClient, ModelError
from mqc_qcr.contracts import Endpoint


def test_retry_audit_and_secret_redaction(monkeypatch):
    monkeypatch.setattr("mqc_qcr.client.time.sleep", lambda _: None)
    attempts, audit = [], []
    secret = "unit-test-secret-not-a-real-key"
    def respond(request):
        attempts.append(request)
        assert request.headers["Authorization"] == "Bearer " + secret
        if len(attempts) == 1:
            return httpx.Response(429, text="echo " + secret)
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK " + secret}, "finish_reason": "stop"}]})
    cfg = Endpoint(base_url="http://localhost:9999/v1", model="test-model", api_key=secret)
    answer = ModelClient(cfg, audit.append, transport=httpx.MockTransport(respond)).call("hello")
    assert len(attempts) == 2 and len(audit) == 2
    assert secret not in json.dumps(audit) and secret not in answer
    assert audit[0]["error"]["code"] == "HTTP_ERROR"


@pytest.mark.parametrize("status,code", [(401,"AUTH_FAILED"),(403,"AUTH_FAILED"),(404,"HTTP_ERROR")])
def test_permanent_errors_not_retried(status, code):
    calls = []
    def respond(request):
        calls.append(1)
        return httpx.Response(status, text="failed")
    with pytest.raises(ModelError) as exc:
        ModelClient(Endpoint(base_url="http://localhost/v1", model="x"), transport=httpx.MockTransport(respond)).call("test")
    assert exc.value.code == code and len(calls) == 1


def test_timeout_and_truncation_retained(monkeypatch):
    monkeypatch.setattr("mqc_qcr.client.time.sleep", lambda _: None)
    audit = []
    def timeout(request):
        raise httpx.ReadTimeout("untrusted detail")
    with pytest.raises(ModelError, match="超时"):
        ModelClient(Endpoint(base_url="http://localhost/v1", model="x", retries=1), audit.append, transport=httpx.MockTransport(timeout)).call("test")
    assert len(audit) == 2
    assert "untrusted detail" not in json.dumps(audit)
    def truncated(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "partial"}, "finish_reason": "length"}]})
    with pytest.raises(ModelError) as exc:
        ModelClient(Endpoint(base_url="http://localhost/v1", model="x"), audit.append, transport=httpx.MockTransport(truncated)).call("test")
    assert exc.value.code == "TRUNCATED" and "partial" in audit[-1]["raw_response"]
