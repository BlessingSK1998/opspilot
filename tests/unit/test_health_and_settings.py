import json
import logging

import pytest
from fastapi.testclient import TestClient

from opspilot.api.app import create_app
from opspilot.logging_setup import JsonFormatter, run_id_var
from opspilot.settings import Settings


def test_health_ok() -> None:
    res = TestClient(create_app()).get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_provider_is_mock_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert Settings(_env_file=None).llm_provider == "mock"  # type: ignore[call-arg]


def test_provider_is_openai_with_key() -> None:
    s = Settings(_env_file=None, openai_api_key="sk-test")  # type: ignore[call-arg,arg-type]
    assert s.llm_provider == "openai"


def test_json_log_has_run_id() -> None:
    token = run_id_var.set("run-123")
    try:
        rec = logging.LogRecord("t", logging.INFO, "f", 1, "hello", None, None)
        out = json.loads(JsonFormatter().format(rec))
    finally:
        run_id_var.reset(token)
    assert out["run_id"] == "run-123"
    assert out["msg"] == "hello"
