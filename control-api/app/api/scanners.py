"""`GET /scanners` -- реестр сканеров для UI.

Отдаёт регистрации из `app.scanner_registry` вместе с живой config-схемой
каждого сканера: control-api спрашивает у сервиса `GET /schema` (короткий
таймаут, TTL-кэш), обогащает поля типа `llm_model` опциями из БД и помечает
недоступные сканеры. Фронт по этому ответу строит формы создания сканирований
-- никаких списков сканеров и опций на фронте.
"""
import time
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from sqlmodel import Session, select

from app.db import engine
from app.models import AgentConfig, AssetKind, LLMModel, McpAsset
from app.scanner_registry import REGISTRY, ScannerRegistration

router = APIRouter(prefix="/scanners", tags=["scanners"])

_SCHEMA_TIMEOUT = 2.0
_CACHE_TTL = 30.0
# scanner_url -> (monotonic время загрузки, схема или None если недоступен)
_schema_cache: dict[str, tuple[float, Optional[dict]]] = {}


def _fetch_schema(reg: ScannerRegistration) -> Optional[dict]:
    """Схема сканера `{"type": ..., "fields": [...]}` или None, если сервис
    недоступен/не отдал схему."""
    now = time.monotonic()
    cached = _schema_cache.get(reg.url)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]
    schema: Optional[dict] = None
    try:
        response = httpx.get(f"{reg.url}/schema", timeout=_SCHEMA_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and isinstance(payload.get("fields"), list):
            schema = payload
    except (httpx.HTTPError, ValueError):
        schema = None
    _schema_cache[reg.url] = (now, schema)
    return schema


def _enrich_llm_model_fields(schema: Optional[dict]) -> Optional[dict]:
    """Поле типа `llm_model` сканер описать сам не может -- модели живут в БД
    control-api. Заполняем options списком `LLMModel` на момент запроса."""
    if not schema:
        return schema
    fields = schema.get("fields", [])
    if not any(field.get("type") == "llm_model" for field in fields):
        return schema
    with Session(engine) as session:
        models = session.exec(select(LLMModel)).all()
        options = [{"value": model.id, "label": model.name} for model in models]
    enriched = {**schema, "fields": [dict(field) for field in fields]}
    for field in enriched["fields"]:
        if field.get("type") == "llm_model":
            field["options"] = options
    return enriched


def _asset_capabilities(session: Session, kind: AssetKind, asset) -> set[str]:
    """Свойства актива, от которых зависит применимость сканеров:
    code -- есть исходники; live -- есть работающий сервис; deployable --
    платформа сама поднимет сервис при скане (агенты из репозитория)."""
    capabilities: set[str] = set()
    if kind == AssetKind.AGENT:
        if (getattr(asset, "source", None) or "repository") == "repository":
            capabilities |= {"code", "deployable"}
        else:
            capabilities.add("live")
    elif kind == AssetKind.MCP:
        target_kind = (asset.config or {}).get("kind")
        if target_kind == "remote":
            capabilities.add("live")
        else:
            capabilities.add("code")
            # Настроенный деплой -- обещание живого сервиса для динамики.
            if asset.deploy:
                capabilities.add("live")
    return capabilities


def _filter_mcp_schema_by_target(schema: dict, target_kind: str, reason: str) -> dict:
    """Движки scanner-mcp применимы к разным режимам цели (modes в каталоге):
    SAST -- source/repository/bundle, каталог и динамика -- remote.
    Неприменимые движки помечаются недоступными с причиной."""
    schema = {**schema, "fields": [dict(field) for field in schema.get("fields", [])]}
    for field in schema["fields"]:
        if field.get("name") != "scanner_ids":
            continue
        options = []
        for option in field.get("options", []):
            modes = option.get("modes") or []
            applicable = target_kind in modes
            updated = dict(option)
            if not applicable:
                updated["available"] = False
                updated["description"] = f"{option.get('description', '')} · не применим к источнику «{reason}»".strip(" ·")
            options.append(updated)
        field["options"] = options
    return schema


@router.get("")
def list_scanners(
    asset_kind: Optional[AssetKind] = None,
    asset_id: Optional[int] = None,
) -> list[dict]:
    """Реестр сканеров. С `asset_kind`+`asset_id` -- ещё и применимость к
    конкретному активу: `available_for_asset` и причина, а в схеме MCP
    движки помечаются по режиму цели (remote/repository/bundle)."""
    capabilities: Optional[set[str]] = None
    mcp_target_kind: Optional[str] = None
    if asset_kind is not None and asset_id is not None:
        model = {AssetKind.AGENT: AgentConfig, AssetKind.MCP: McpAsset}.get(asset_kind)
        with Session(engine) as session:
            asset = session.get(model, asset_id) if model else None
            if not asset:
                raise HTTPException(status_code=404, detail="Актив не найден")
            capabilities = _asset_capabilities(session, asset_kind, asset)
            if asset_kind == AssetKind.MCP:
                mcp_target_kind = (asset.config or {}).get("kind")

    target_names = {"remote": "удалённый сервер", "repository": "репозиторий", "bundle": "MCPB-архив"}
    result = []
    for reg in REGISTRY:
        schema = _enrich_llm_model_fields(_fetch_schema(reg))
        entry = {
            "type": reg.type.value,
            "name": reg.name,
            "description": reg.description,
            "service": reg.service,
            "asset_kinds": list(reg.asset_kinds),
            "phases": list(reg.phases),
            "available": schema is not None,
            "config_schema": schema,
            "available_for_asset": None,
            "unavailable_reason": None,
        }
        if capabilities is not None:
            kind_ok = asset_kind in reg.asset_kinds
            requirements_ok = reg.available_for(capabilities)
            entry["available_for_asset"] = kind_ok and requirements_ok
            if not entry["available_for_asset"]:
                if not kind_ok:
                    kinds = ", ".join(reg.asset_kinds)
                    entry["unavailable_reason"] = f"сканер работает только с активами: {kinds}"
                else:
                    missing = {
                        "code": "у актива нет исходников",
                        "live": "у актива нет работающего сервиса (и платформа не может его поднять)",
                        "deployable": "платформа не может поднять этот актив сама (он не из репозитория)",
                    }
                    need = ", ".join(sorted(reg.requirements))
                    entry["unavailable_reason"] = f"требуется {need}: {missing.get(next(iter(reg.requirements)), need)}"
        if schema and mcp_target_kind and reg.type.value == "mcp":
            entry["config_schema"] = _filter_mcp_schema_by_target(schema, mcp_target_kind, target_names.get(mcp_target_kind, mcp_target_kind))
        result.append(entry)
    return result
