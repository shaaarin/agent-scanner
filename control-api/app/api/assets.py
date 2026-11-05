"""`GET /assets` -- единый список активов раздела «Активы».

Активы трёх видов живут в разных таблицах (AgentConfig, McpAsset,
SkillAsset); этот эндпоинт объединяет их для дашборда и списков. Полный CRUD
-- в профильных эндпоинтах: /agent-configs, /mcp-assets, /skill-assets.
"""
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.auth.deps import accessible_org_ids, get_caller, Caller
from app.db import get_session
from app.models import AgentConfig, AssetKind, McpAsset, SkillAsset
from app.schemas import AssetRead

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[AssetRead])
def list_assets(
    kind: AssetKind | None = None,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
):
    org_ids = accessible_org_ids(session, caller)

    def _agents() -> list[AssetRead]:
        query = select(AgentConfig)
        if org_ids is not None:
            query = query.where(AgentConfig.organization_id.in_(org_ids))
        return [
            AssetRead(kind=AssetKind.AGENT, id=agent.id, name=agent.name, organization_id=agent.organization_id,
                      description=agent.agent_purpose, created_at=agent.created_at)
            for agent in session.exec(query).all()
        ]

    def _mcp() -> list[AssetRead]:
        query = select(McpAsset)
        if org_ids is not None:
            query = query.where(McpAsset.organization_id.in_(org_ids))
        return [
            AssetRead(kind=AssetKind.MCP, id=asset.id, name=asset.name, organization_id=asset.organization_id,
                      description=asset.description, created_at=asset.created_at)
            for asset in session.exec(query).all()
        ]

    def _skills() -> list[AssetRead]:
        query = select(SkillAsset)
        if org_ids is not None:
            query = query.where(SkillAsset.organization_id.in_(org_ids))
        return [
            AssetRead(kind=AssetKind.SKILL, id=asset.id, name=asset.name, organization_id=asset.organization_id,
                      description=asset.description, created_at=asset.created_at)
            for asset in session.exec(query).all()
        ]

    assets: list[AssetRead] = []
    if kind is None or kind == AssetKind.AGENT:
        assets.extend(_agents())
    if kind is None or kind == AssetKind.MCP:
        assets.extend(_mcp())
    if kind is None or kind == AssetKind.SKILL:
        assets.extend(_skills())
    assets.sort(key=lambda asset: asset.created_at, reverse=True)
    return assets
