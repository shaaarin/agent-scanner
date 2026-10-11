"""`GET /assets` -- единый список активов раздела «Активы».

Активы трёх видов живут в разных таблицах (AgentConfig, McpAsset,
SkillAsset); этот эндпоинт объединяет их для дашборда и списков. Полный CRUD
-- в профильных эндпоинтах: /agent-configs, /mcp-assets, /skill-assets.
"""
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db import get_session
from app.models import AgentConfig, AssetKind, McpAsset, SkillAsset
from app.schemas import AssetRead

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[AssetRead])
def list_assets(kind: AssetKind | None = None, session: Session = Depends(get_session)):
    assets: list[AssetRead] = []
    if kind is None or kind == AssetKind.AGENT:
        assets.extend(
            AssetRead(kind=AssetKind.AGENT, id=agent.id, name=agent.name, description=agent.agent_purpose, created_at=agent.created_at)
            for agent in session.exec(select(AgentConfig)).all()
        )
    if kind is None or kind == AssetKind.MCP:
        assets.extend(
            AssetRead(kind=AssetKind.MCP, id=asset.id, name=asset.name, description=asset.description, created_at=asset.created_at)
            for asset in session.exec(select(McpAsset)).all()
        )
    if kind is None or kind == AssetKind.SKILL:
        assets.extend(
            AssetRead(kind=AssetKind.SKILL, id=asset.id, name=asset.name, description=asset.description, created_at=asset.created_at)
            for asset in session.exec(select(SkillAsset)).all()
        )
    assets.sort(key=lambda asset: asset.created_at, reverse=True)
    return assets
