"""Фикстуры тестов scanner-skills.

Вместо control-api -- маленький HTTP-сервер в памяти с тем же контрактом,
который читает сканер (`GET/PATCH /scans/{id}`, `GET /scans`,
`POST /scans/{id}/logs`). LLM здесь не участвует. Клиент сканера
(`control_client._client`) перенаправляется на этот сервер.
"""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app import control_client, runner


class FakeControlApi:
    def __init__(self):
        self.scans: dict[int, dict] = {}
        self.logs: dict[int, list[dict]] = {}
        self.events: list[tuple] = []  # ("patch"|"log", scan_id, payload) по порядку
        self.rejected_logs: list[dict] = []
        self.archives: dict[int, bytes] = {}  # GET /skill-assets/{id}/content
        self.lock = threading.Lock()

    def add_scan(self, scan_id: int, **fields) -> dict:
        scan = {
            "id": scan_id,
            "type": "agent_skills",
            "asset_kind": "skill",
            "asset_id": 1,
            "status": "running",
            "phase": "Запуск",
            "config": json.dumps({"source": ZIP_SOURCE}),
            "results": None,
            "error": None,
        }
        scan.update(fields)
        self.scans[scan_id] = scan
        self.logs[scan_id] = []
        return scan

    def messages(self, scan_id: int) -> list[str]:
        return [log["message"] for log in self.logs[scan_id]]

    def phases(self, scan_id: int) -> list[str]:
        return [p["phase"] for kind, sid, p in self.events if kind == "patch" and sid == scan_id and "phase" in p]


LOG_LEVELS = {"info", "success", "error"}
def make_zip(files: dict[str, str | bytes]) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def skill_md(name: str) -> str:
    return f"---\nname: {name}\ndescription: инертный тестовый скилл\n---\n\nВыведи `echo ok`.\n"


def zip_source(content: bytes, asset_id: int = 1) -> dict:
    import hashlib

    return {"kind": "zip", "asset_id": asset_id, "archive_filename": "pack.zip", "archive_sha256": hashlib.sha256(content).hexdigest()}


ZIP_SOURCE = {"kind": "zip", "asset_id": 1, "archive_filename": "pack.zip", "archive_sha256": "ab" * 32}


def _handler(api: FakeControlApi):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, code: int, payload) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length) or b"{}")

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path == "/scans":
                query = parse_qs(url.query)
                status = query.get("status", [None])[0]
                scan_type = query.get("scan_type", [None])[0]
                with api.lock:
                    found = [
                        s for s in api.scans.values()
                        if (status is None or s["status"] == status) and (scan_type is None or s["type"] == scan_type)
                    ]
                return self._reply(200, found)
            match = re.fullmatch(r"/skill-assets/(\d+)/content", url.path)
            if match:
                content = api.archives.get(int(match.group(1)))
                if content is None:
                    return self._reply(404, {"detail": "Skill-актив не найден"})
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            match = re.fullmatch(r"/scans/(\d+)", url.path)
            if match and int(match.group(1)) in api.scans:
                return self._reply(200, api.scans[int(match.group(1))])
            self._reply(404, {"detail": "Scan not found"})

        def do_PATCH(self):  # noqa: N802
            match = re.fullmatch(r"/scans/(\d+)", self.path)
            if not match or int(match.group(1)) not in api.scans:
                return self._reply(404, {"detail": "Scan not found"})
            scan_id, payload = int(match.group(1)), self._body()
            with api.lock:
                api.scans[scan_id].update(payload)
                api.events.append(("patch", scan_id, payload))
            self._reply(200, api.scans[scan_id])

        def do_POST(self):  # noqa: N802
            match = re.fullmatch(r"/scans/(\d+)/logs", self.path)
            if not match or int(match.group(1)) not in api.scans:
                return self._reply(404, {"detail": "Scan not found"})
            scan_id, payload = int(match.group(1)), self._body()
            # Как ScanLogLevel в control-api: другие уровни -- 422.
            if payload.get("level") not in LOG_LEVELS:
                with api.lock:
                    api.rejected_logs.append(payload)
                return self._reply(422, {"detail": "invalid level"})
            with api.lock:
                api.logs[scan_id].append(payload)
                api.events.append(("log", scan_id, payload))
            self._reply(200, payload)

        def log_message(self, *args):
            pass

    return Handler


@pytest.fixture
def api(monkeypatch):
    fake = FakeControlApi()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(fake))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = httpx.Client(base_url=f"http://127.0.0.1:{server.server_address[1]}", timeout=5.0)
    monkeypatch.setattr(control_client, "_client", client)
    # Каждому тесту -- свежие слоты и пустой список выполняемых сканов.
    monkeypatch.setattr(runner, "_slots", threading.BoundedSemaphore(runner.MAX_CONCURRENT))
    runner._running.clear()
    yield fake
    server.shutdown()
    assert not fake.rejected_logs, f"control-api отверг строки журнала: {fake.rejected_logs}"
    client.close()


@pytest.fixture(scope="session")
def built_rules(tmp_path_factory):
    """Свои правила как в образе: rules/yara + пак Cisco, собранный
    rules/build_pack.py (D-35)."""
    import shutil
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "rules"
    sys.path.insert(0, str(root))
    import build_pack

    target = tmp_path_factory.mktemp("rules")
    shutil.copytree(root / "yara", target / "yara")
    files, rules = build_pack.load(target / "yara")
    build_pack.write_pack(files, rules, target / "cisco-pack")
    return target


@pytest.fixture(autouse=True)
def rules_env(built_rules, monkeypatch):
    monkeypatch.setenv("SKILLS_RULES_DIR", str(built_rules))
    return built_rules


@pytest.fixture(scope="session")
def image():
    """Собранный образ scanner-skills (`SKILLS_IMAGE`); без docker/образа -- skip."""
    import os
    import shutil
    import subprocess

    name = os.environ.get("SKILLS_IMAGE", "agent-scanner-scanner-skills")
    if not shutil.which("docker"):
        pytest.skip("docker не найден")
    if subprocess.run(["docker", "image", "inspect", name], capture_output=True).returncode != 0:
        pytest.skip(f"образ {name} не собран (docker compose build scanner-skills)")
    return name
