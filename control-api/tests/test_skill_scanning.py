"""Подзадача 2 SKILLSS.md: подключение skill-активов к сканированию (D-38,
D-39, D-46). Сканер-заглушку заменяет настоящий локальный HTTP-сервер с
контрактом scanner-skills (`/schema`, `/run/{id}`) -- LLM здесь не участвует."""
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from sqlmodel import Session

from app.api import scanners as scanners_api
from app.api.scanners import _asset_capabilities
from app.db import engine
from app.models import AssetKind, ScanType, SkillAsset, SkillSource
from app.scanner_registry import REGISTRY, find, for_asset_kind

from conftest import SKILL_MD, TEST_ORG_ID, make_zip

SKILLS_SCHEMA = {
    "type": "agent_skills",
    "fields": [
        {
            "name": "engines",
            "type": "enum_multi",
            "label": "Движки",
            "options": [{"value": "cisco", "label": "Cisco"}, {"value": "skillspector", "label": "SkillSpector"}],
        }
    ],
}


class _FakeSkillsScanner(BaseHTTPRequestHandler):
    """Минимальный сервис с контрактом scanner-skills."""

    runs: list[str] = []

    def _reply(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/schema":
            self._reply(200, SKILLS_SCHEMA)
        else:
            self._reply(404, {})

    def do_POST(self):  # noqa: N802
        if self.path.startswith("/run/"):
            type(self).runs.append(self.path)
            self._reply(200, {"status": "started"})
        else:
            self._reply(404, {})

    def log_message(self, *args):  # тише в выводе pytest
        pass


@pytest.fixture
def skills_service(monkeypatch):
    """Поднимает сервис на свободном порту и направляет на него
    SCANNER_SKILLS_URL; остальные сканеры -- на закрытый порт (недоступны)."""
    _FakeSkillsScanner.runs = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeSkillsScanner)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for reg in REGISTRY:
        monkeypatch.setenv(reg.url_env, "http://127.0.0.1:9")
    monkeypatch.setenv("SCANNER_SKILLS_URL", f"http://127.0.0.1:{server.server_address[1]}")
    scanners_api._schema_cache.clear()
    yield _FakeSkillsScanner
    server.shutdown()
    scanners_api._schema_cache.clear()


def _create_scan(client, asset: dict, *, kind: str = "skill", scan_type: str = "agent_skills", config: dict | None = None):
    return client.post(
        "/scans",
        json={
            "name": "скан скиллов",
            "type": scan_type,
            "asset_kind": kind,
            "asset_id": asset["id"],
            "session_id": "s-1",
            "config": config or {},
        },
    )


# --- реестр -----------------------------------------------------------------


def test_registry_has_agent_skills():
    reg = find(ScanType.AGENT_SKILLS)
    assert reg is not None
    assert reg.service == "scanner-skills"
    assert reg.asset_kinds == ("skill",)
    assert reg.requirements == frozenset({"code"})
    assert reg.phases[0] == "В очереди" and reg.phases[-1] == "Завершено"
    assert "Получение исходников" in reg.phases and "Статический анализ" in reg.phases


def test_registry_url_default_and_env(monkeypatch):
    reg = find(ScanType.AGENT_SKILLS)
    monkeypatch.delenv("SCANNER_SKILLS_URL", raising=False)
    assert reg.url == "http://scanner-skills:8000"
    monkeypatch.setenv("SCANNER_SKILLS_URL", "http://elsewhere:1")
    assert reg.url == "http://elsewhere:1"


def test_only_skills_scanner_for_skill_assets():
    assert [reg.type for reg in for_asset_kind("skill")] == [ScanType.AGENT_SKILLS]
    assert ScanType.AGENT_SKILLS not in {reg.type for reg in for_asset_kind("agent")}
    assert ScanType.AGENT_SKILLS not in {reg.type for reg in for_asset_kind("mcp")}


# --- свойства актива ----------------------------------------------------------


@pytest.mark.parametrize("source", [SkillSource.ZIP, SkillSource.REPOSITORY])
def test_skill_capabilities_are_code(source):
    with Session(engine) as session:
        caps = _asset_capabilities(session, AssetKind.SKILL, SkillAsset(organization_id=TEST_ORG_ID, name="x", source=source))
    assert caps == {"code"}


# --- GET /scanners ------------------------------------------------------------


def test_scanners_for_skill_asset(client, zip_asset, skills_service):
    response = client.get("/scanners", params={"asset_kind": "skill", "asset_id": zip_asset["id"]})
    assert response.status_code == 200, response.text
    by_type = {entry["type"]: entry for entry in response.json()}
    skills = by_type["agent_skills"]
    assert skills["available"] is True
    assert skills["available_for_asset"] is True
    assert skills["unavailable_reason"] is None
    assert skills["config_schema"] == SKILLS_SCHEMA
    assert skills["phases"][0] == "В очереди"
    for scan_type, entry in by_type.items():
        if scan_type != "agent_skills":
            assert entry["available_for_asset"] is False
            assert "skill" not in entry["asset_kinds"]
            assert entry["unavailable_reason"].startswith("сканер работает только с активами")


def test_scanners_unknown_skill_asset_404(client, skills_service):
    response = client.get("/scanners", params={"asset_kind": "skill", "asset_id": 999})
    assert response.status_code == 404


def test_scanners_for_agent_not_affected(client, agent_asset, skills_service):
    response = client.get("/scanners", params={"asset_kind": "agent", "asset_id": agent_asset["id"]})
    assert response.status_code == 200
    by_type = {entry["type"]: entry for entry in response.json()}
    assert by_type["agent_skills"]["available_for_asset"] is False
    assert by_type["code_scan"]["available_for_asset"] is True
    assert by_type["deep_team"]["available_for_asset"] is True


def test_scanners_unavailable_service_marked(client, zip_asset, monkeypatch, skills_service):
    monkeypatch.setenv("SCANNER_SKILLS_URL", "http://127.0.0.1:9")
    scanners_api._schema_cache.clear()
    by_type = {e["type"]: e for e in client.get("/scanners").json()}
    assert by_type["agent_skills"]["available"] is False
    assert by_type["agent_skills"]["config_schema"] is None


# --- GET /skill-assets/{id}/content ------------------------------------------


def test_content_returns_archive(client, zip_asset, zip_bytes):
    response = client.get(f"/skill-assets/{zip_asset['id']}/content")
    assert response.status_code == 200
    assert response.content == zip_bytes
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["x-archive-sha256"] == hashlib.sha256(zip_bytes).hexdigest()
    assert response.headers["x-archive-sha256"] == zip_asset["archive_sha256"]
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="skills.zip"')
    assert "filename*=UTF-8''my%20skills.zip" in disposition


def test_content_for_repository_asset_409(client, repo_asset):
    response = client.get(f"/skill-assets/{repo_asset['id']}/content")
    assert response.status_code == 409


def test_content_unknown_asset_404(client):
    assert client.get("/skill-assets/999/content").status_code == 404


def test_content_zip_asset_without_blob_404(client):
    with Session(engine) as session:
        asset = SkillAsset(organization_id=TEST_ORG_ID, name="empty", source=SkillSource.ZIP, archive_filename="x.zip")
        session.add(asset)
        session.commit()
        asset_id = asset.id
    assert client.get(f"/skill-assets/{asset_id}/content").status_code == 404


def test_read_endpoints_do_not_leak_blob_or_token(client, zip_asset, repo_asset):
    for asset in client.get("/skill-assets").json():
        assert "archive" not in asset
        assert "git_access_token" not in asset


# --- POST /scans ---------------------------------------------------------------


def test_create_scan_zip_snapshot(client, zip_asset):
    response = _create_scan(client, zip_asset, config={"engines": ["cisco"]})
    assert response.status_code == 200, response.text
    scan = response.json()
    assert scan["type"] == "agent_skills"
    assert scan["asset_kind"] == "skill"
    assert scan["asset_id"] == zip_asset["id"]
    assert scan["agent_config_id"] is None
    assert scan["status"] == "pending"
    config = json.loads(scan["config"])
    assert config["engines"] == ["cisco"]
    assert config["source"] == {
        "kind": "zip",
        "asset_id": zip_asset["id"],
        "archive_filename": "my skills.zip",
        "archive_sha256": zip_asset["archive_sha256"],
    }


def test_create_scan_repository_snapshot_with_token(client, repo_asset):
    scan = _create_scan(client, repo_asset).json()
    assert json.loads(scan["config"])["source"] == {
        "kind": "repository",
        "git_repo_url": "https://git.example.invalid/org/skills.git",
        "git_ref": "v1",
        "git_access_token": "tok-123",
    }


def test_create_scan_repository_default_ref(client):
    asset = client.post(
        "/skill-assets", json={"organization_id": TEST_ORG_ID, "name": "r2", "git_repo_url": "https://git.example.invalid/x.git", "git_ref": ""}
    ).json()
    source = json.loads(_create_scan(client, asset).json()["config"])["source"]
    assert source["git_ref"] == "main"
    assert source["git_access_token"] is None


def test_create_scan_client_cannot_override_source(client, zip_asset):
    forged = {"kind": "repository", "git_repo_url": "https://evil.invalid/x.git"}
    scan = _create_scan(client, zip_asset, config={"source": forged}).json()
    assert json.loads(scan["config"])["source"]["kind"] == "zip"


def test_snapshot_survives_asset_edit(client, repo_asset):
    scan = _create_scan(client, repo_asset).json()
    client.put(f"/skill-assets/{repo_asset['id']}", json={"git_ref": "v2", "git_access_token": "new"})
    stored = client.get(f"/scans/{scan['id']}").json()
    source = json.loads(stored["config"])["source"]
    assert source["git_ref"] == "v1"
    assert source["git_access_token"] == "tok-123"
    # а новый скан видит правку
    fresh = json.loads(_create_scan(client, repo_asset).json()["config"])["source"]
    assert fresh["git_ref"] == "v2"


def test_create_scan_repository_without_url_422(client):
    with Session(engine) as session:
        asset = SkillAsset(organization_id=TEST_ORG_ID, name="broken", source=SkillSource.REPOSITORY, git_repo_url="  ")
        session.add(asset)
        session.commit()
        asset_dict = {"id": asset.id}
    response = _create_scan(client, asset_dict)
    assert response.status_code == 422
    assert "git-репозиторий" in response.json()["detail"]


def test_create_scan_zip_without_archive_422(client):
    with Session(engine) as session:
        asset = SkillAsset(organization_id=TEST_ORG_ID, name="noblob", source=SkillSource.ZIP)
        session.add(asset)
        session.commit()
        asset_dict = {"id": asset.id}
    response = _create_scan(client, asset_dict)
    assert response.status_code == 422
    assert "архив" in response.json()["detail"]


def test_create_scan_unknown_skill_asset_422(client):
    assert _create_scan(client, {"id": 999}).status_code == 422


def test_other_scanner_on_skill_asset_422(client, zip_asset):
    response = _create_scan(client, zip_asset, scan_type="code_scan")
    assert response.status_code == 422


def test_skills_scanner_on_agent_asset_422(client, agent_asset):
    response = _create_scan(client, agent_asset, kind="agent")
    assert response.status_code == 422


def test_agent_scan_unchanged(client, agent_asset):
    response = _create_scan(client, agent_asset, kind="agent", scan_type="ai_code_scan", config={"min_severity": "low"})
    assert response.status_code == 200, response.text
    scan = response.json()
    assert scan["agent_config_id"] == agent_asset["id"]
    assert json.loads(scan["config"]) == {"min_severity": "low"}


def test_list_scans_by_skill_asset(client, zip_asset, repo_asset):
    _create_scan(client, zip_asset)
    _create_scan(client, repo_asset)
    scans = client.get("/scans", params={"asset_kind": "skill", "asset_id": zip_asset["id"]}).json()
    assert len(scans) == 1 and scans[0]["asset_id"] == zip_asset["id"]


def test_delete_skill_asset_blocked_by_scan(client, zip_asset):
    scan = _create_scan(client, zip_asset).json()
    assert client.delete(f"/skill-assets/{zip_asset['id']}").status_code == 409
    client.delete(f"/scans/{scan['id']}")
    assert client.delete(f"/skill-assets/{zip_asset['id']}").status_code == 204


# --- POST /scans/{id}/start ----------------------------------------------------


def test_start_scan_calls_skills_service(client, zip_asset, skills_service):
    scan = _create_scan(client, zip_asset).json()
    response = client.post(f"/scans/{scan['id']}/start")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "running"
    assert skills_service.runs == [f"/run/{scan['id']}"]
    logs = client.get(f"/scans/{scan['id']}/logs").json()
    assert logs and logs[0]["message"] == "Сканирование поставлено в очередь"


def test_start_scan_service_down_fails(client, zip_asset, monkeypatch):
    monkeypatch.setenv("SCANNER_SKILLS_URL", "http://127.0.0.1:9")
    scan = _create_scan(client, zip_asset).json()
    result = client.post(f"/scans/{scan['id']}/start").json()
    assert result["status"] == "failed"
    assert result["error"].startswith("scanner-skills недоступен")


def test_uploaded_archive_roundtrip_multiple_skills(client):
    content = make_zip({"a/SKILL.md": SKILL_MD, "b/SKILL.md": SKILL_MD, "b/scripts/run.sh": "echo ok\n"})
    asset = client.post(
        "/skill-assets/upload", data={"organization_id": TEST_ORG_ID, "name": "pack"}, files={"file": ("pack.zip", content, "application/zip")}
    ).json()
    scan = _create_scan(client, asset).json()
    source = json.loads(scan["config"])["source"]
    fetched = client.get(f"/skill-assets/{source['asset_id']}/content")
    assert hashlib.sha256(fetched.content).hexdigest() == source["archive_sha256"]


def test_skill_queue_publish_failure_leaves_scan_retryable(client, zip_asset, monkeypatch):
    import pika
    from app.api import scans

    monkeypatch.setenv("RABBITMQ_URL", "amqp://test")
    scan_id = _create_scan(client, zip_asset).json()["id"]

    def unavailable(*args):
        raise pika.exceptions.AMQPConnectionError("offline")

    monkeypatch.setattr(scans, "publish", unavailable)
    assert client.post(f"/scans/{scan_id}/start").status_code == 503
    assert client.get(f"/scans/{scan_id}").json()["status"] == "pending"

    deliveries = []
    monkeypatch.setattr(scans, "publish", lambda *args: deliveries.append(args))
    assert client.post(f"/scans/{scan_id}/start").json()["phase"] == "В очереди"
    assert client.post(f"/scans/{scan_id}/start").status_code == 400
    assert len(deliveries) == 1
    assert deliveries[0][1] == scan_id
