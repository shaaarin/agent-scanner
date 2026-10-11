"""CRUD активов «MCP» (раздел «Активы», вкладка MCP).

Актив -- цель тестирования: работающий сервер, git-репозиторий или
загруженный MCPB. Конфиг валидируется тем же `MCPTarget`-union, что и цели
сканов, так что к моменту запуска scanner-mcp получает уже проверенные поля.
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.mcp_config import validate_mcp_config
from app.models import MCPArtifact, McpAsset, Scan
from app.schemas import McpAssetCreate, McpAssetUpdate

router = APIRouter(prefix="/mcp-assets", tags=["mcp-assets"])


def _check_target_artifact(config: dict, session: Session) -> None:
    if config.get("kind") == "bundle":
        artifact_id = config.get("artifact_id")
        if not artifact_id or not session.get(MCPArtifact, artifact_id):
            raise HTTPException(status_code=422, detail="Указанный MCPB-артефакт не найден")


def _validate_target(target: dict) -> None:
    """Провалидировать цель «как сканер»: собрать минимальный конфиг скана и
    прогнать через ту же проверку, что стоит на запуске MCP-скана."""
    validate_mcp_config(json.dumps({"target": target}, ensure_ascii=False))


@router.post("", response_model=McpAsset)
def create_mcp_asset(payload: McpAssetCreate, session: Session = Depends(get_session)):
    existing = session.exec(select(McpAsset).where(McpAsset.name == payload.name)).first()
    if existing:
        raise HTTPException(status_code=409, detail="Актив с таким именем уже существует")
    target = payload.config.model_dump(mode="json")
    _check_target_artifact(target, session)
    # Отклоняем невалидные цели сразу, а не при создании первого скана.
    _validate_target(target)
    asset = McpAsset(
        name=payload.name,
        description=payload.description,
        config=target,
        deploy=payload.deploy.model_dump(exclude_none=True) if payload.deploy else None,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.get("", response_model=list[McpAsset])
def list_mcp_assets(session: Session = Depends(get_session)):
    return session.exec(select(McpAsset).order_by(McpAsset.created_at.desc())).all()


@router.get("/{asset_id}", response_model=McpAsset)
def get_mcp_asset(asset_id: int, session: Session = Depends(get_session)):
    asset = session.get(McpAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="MCP-актив не найден")
    return asset


@router.put("/{asset_id}", response_model=McpAsset)
def update_mcp_asset(asset_id: int, payload: McpAssetUpdate, session: Session = Depends(get_session)):
    asset = session.get(McpAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="MCP-актив не найден")
    updates = payload.model_dump(exclude_unset=True)
    if "deploy" in updates:
        # Из pydantic-модели в JSON-словарь (пустые значения выкидываем).
        updates["deploy"] = updates["deploy"].model_dump(exclude_none=True) if updates["deploy"] else None
    new_name = updates.get("name")
    if new_name and new_name != asset.name:
        existing = session.exec(select(McpAsset).where(McpAsset.name == new_name)).first()
        if existing:
            raise HTTPException(status_code=409, detail="Актив с таким именем уже существует")
    if "config" in updates:
        target = updates["config"]
        _check_target_artifact(target, session)
        _validate_target(target)
    for key, value in updates.items():
        setattr(asset, key, value)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.delete("/{asset_id}", status_code=204)
def delete_mcp_asset(asset_id: int, session: Session = Depends(get_session)):
    asset = session.get(McpAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="MCP-актив не найден")
    scans = session.exec(
        select(Scan).where(Scan.asset_kind == "mcp").where(Scan.asset_id == asset_id)
    ).all()
    if scans:
        raise HTTPException(
            status_code=409,
            detail=f"У MCP-актива есть сканирования ({len(scans)}): сначала удалите их",
        )
    session.delete(asset)
    session.commit()
