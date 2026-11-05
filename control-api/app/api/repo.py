"""Разбор репозитория агента для мастера конфигурации (ветки, Dockerfile,
.env.example). Живёт в control-api, чтобы браузер общался только с ним -- под
сессией auth, без публикации launcher'а наружу. До создания актива агент ещё
не в базе (проксировать по id нечего), поэтому мастер шлёт сырой git-URL и
токен, а control-api переадресует их launcher'у по внутренней сети: git-логика
(repo_inspect) живёт там."""

import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.deps import get_caller

LAUNCHER_URL = os.environ.get("LAUNCHER_URL", "http://launcher:8000")

router = APIRouter(
    prefix="/repo",
    tags=["repo"],
    # Достаточно факта входа: актива ещё нет, организации и роли не применимы.
    dependencies=[Depends(get_caller)],
)


class RepoBranchesRequest(BaseModel):
    git_repo_url: str
    git_access_token: str | None = None


class RepoInspectRequest(BaseModel):
    git_repo_url: str
    git_ref: str
    git_access_token: str | None = None


def _forward(path: str, payload: dict) -> dict:
    """POST в launcher со сквозной передачей ответа: его код и detail -- то,
    что мастер и показывал при прямых вызовах. Инспекция клонирует репозиторий
    и может быть долгой."""
    try:
        with httpx.Client(timeout=httpx.Timeout(600.0, connect=5.0)) as client:
            response = client.post(f"{LAUNCHER_URL}{path}", json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"launcher недоступен: {exc}") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail") or response.text
        except ValueError:
            detail = response.text
        raise HTTPException(status_code=response.status_code, detail=detail)
    return response.json()


@router.post("/branches")
def repo_branches(req: RepoBranchesRequest) -> dict:
    """Ветки репозитория для шага 1 мастера конфигурации агента."""
    return _forward("/repo/branches", req.model_dump())


@router.post("/inspect")
def repo_inspect(req: RepoInspectRequest) -> dict:
    """Dockerfile/.env.example на выбранной ветке для шага 2 мастера."""
    return _forward("/repo/inspect", req.model_dump())
