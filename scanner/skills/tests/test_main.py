"""HTTP-контракт сканера: /health, /schema, /run/{id} (D-05, D-39)."""
import threading
import time

from fastapi.testclient import TestClient

from app import main, runner, stages

client = TestClient(main.app)

# Типы полей, которые понимает форма web (AGENTS.md, реестр сканеров).
FORM_FIELD_TYPES = {"string", "text", "text_list", "integer", "boolean", "enum", "enum_multi", "llm_model", "json"}


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_schema_contract():
    schema = client.get("/schema").json()
    assert schema["type"] == "agent_skills"
    assert all(field["type"] in FORM_FIELD_TYPES for field in schema["fields"])
    (engines,) = schema["fields"]
    assert engines["name"] == "engines"
    assert engines["type"] == "enum_multi"
    assert engines["default"] == ["cisco", "skillspector"]
    assert [o["value"] for o in engines["options"]] == ["cisco", "skillspector"]
    assert all(o["label"] and o["description"] for o in engines["options"])
    # Поля LLM в MVP нет (D-37).
    assert not any(field["type"] == "llm_model" for field in schema["fields"])


def test_run_starts_and_reports_duplicate(api, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(stages, "fetch_sources", lambda ctx: release.wait(10))
    api.add_scan(7)
    first = client.post("/run/7").json()
    second = client.post("/run/7").json()
    assert first == {"status": "started", "scan_id": 7}
    assert second == {"status": "already_running", "scan_id": 7}
    release.set()
    end = time.monotonic() + 10
    while runner.is_running(7) and time.monotonic() < end:
        time.sleep(0.02)
    assert api.scans[7]["status"] == "failed"  # analyze ещё не реализован
    assert api.scans[7]["error"].startswith("Статический анализ ещё не реализован")
