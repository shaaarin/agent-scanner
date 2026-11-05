import asyncio
import os
import time
from typing import Optional

import httpx

CONTROL_API_URL = os.environ.get("CONTROL_API_URL", "http://control-api:8000")
CACHE_TTL_SECONDS = float(os.environ.get("ACTIVE_SCAN_CACHE_TTL", "2"))

_cache: dict[str, tuple[float, Optional[dict]]] = {}
_client = httpx.AsyncClient(
    base_url=CONTROL_API_URL,
    timeout=3.0,
    # Машинный контур: общий секрет сервисов платформы (control-api
    # принимает запросы только с валидным X-Internal-Token или сессией).
    headers={"X-Internal-Token": os.environ.get("INTERNAL_API_TOKEN", "")},
)


async def get_active_scan(session_id: str) -> Optional[dict]:
    cached = _cache.get(session_id)
    now = time.monotonic()
    if cached is not None and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    try:
        resp = await _client.get("/scans/active", params={"session_id": session_id})
        scan = resp.json() if resp.status_code == 200 else None
    except httpx.HTTPError as exc:
        print(f"[control_client] failed to fetch active scan: {exc}")
        scan = cached[1] if cached is not None else None

    _cache[session_id] = (now, scan)
    return scan


async def get_active_injection(scan_id: int) -> Optional[dict]:
    """Директива косвенной инъекции для текущего прогона -- БЕЗ кэша: активный
    прогон меняется от запроса к запросу, и устаревшая директива подложила бы
    инъекцию не в тот прогон."""
    try:
        resp = await _client.get(f"/scans/{scan_id}/injection/active")
        if resp.status_code != 200:
            return None
        return resp.json()
    except httpx.HTTPError as exc:
        print(f"[control_client] failed to fetch active injection: {exc}")
        return None


async def get_agent_config(scan_id: int) -> Optional[dict]:
    try:
        resp = await _client.get(f"/scans/{scan_id}/agent-config")
        return resp.json() if resp.status_code == 200 else None
    except httpx.HTTPError as exc:
        print(f"[control_client] failed to fetch agent config: {exc}")
        return None


async def post_event(event: dict) -> None:
    async def _send() -> None:
        try:
            await _client.post("/events", json=event)
        except httpx.HTTPError as exc:
            print(f"[control_client] failed to post event, falling back to stdout: {exc} -- {event}")

    asyncio.create_task(_send())
