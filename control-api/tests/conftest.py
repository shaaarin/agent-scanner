"""Общие фикстуры тестов control-api (только логика skill-активов, см.
CLAUDE.local.md: pytest -- явное исключение для модуля Agent Skills).

База -- SQLite во временном файле: DATABASE_URL задаётся до импорта app, схема
создаётся `create_all` (alembic и seed из startup не запускаются -- TestClient
без контекстного менеджера lifespan не выполняет). Миграции и PostgreSQL
проверяются живым прогоном в docker compose.
"""
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

_DB_DIR = tempfile.mkdtemp(prefix="control-api-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_DIR}/test.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import SQLModel, Session  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Organization  # noqa: E402

TEST_ORG_ID = 1


@pytest.fixture(autouse=True)
def _fresh_db():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Organization(id=TEST_ORG_ID, name="Test"))
        session.commit()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def make_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


SKILL_MD = "---\nname: demo\ndescription: инертный тестовый скилл\n---\n\nПросто выведи `echo ok`.\n"


@pytest.fixture
def zip_bytes() -> bytes:
    return make_zip({"demo/SKILL.md": SKILL_MD})


@pytest.fixture
def zip_asset(client, zip_bytes) -> dict:
    response = client.post(
        "/skill-assets/upload",
        data={"organization_id": TEST_ORG_ID, "name": "zip-skills", "description": "архив"},
        files={"file": ("my skills.zip", zip_bytes, "application/zip")},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def repo_asset(client) -> dict:
    response = client.post(
        "/skill-assets",
        json={
            "organization_id": TEST_ORG_ID,
            "name": "repo-skills",
            "git_repo_url": "https://git.example.invalid/org/skills.git",
            "git_ref": "v1",
            "git_access_token": "tok-123",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def agent_asset(client) -> dict:
    response = client.post(
        "/agent-configs",
        json={"organization_id": TEST_ORG_ID, "name": "agent-1", "git_repo_url": "https://git.example.invalid/org/agent.git"},
    )
    assert response.status_code == 200, response.text
    return response.json()
