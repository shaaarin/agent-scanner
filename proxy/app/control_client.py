import asyncio
import os
import time
from typing import Optional

import httpx

CONTROL_API_URL = os.environ.get("CONTROL_API_URL", "http://control-api:8000")
CACHE_TTL_SECONDS = float(os.environ.get("ACTIVE_CAMPAIGN_CACHE_TTL", "2"))

_cache: dict[str, tuple[float, Optional[dict]]] = {}
_client = httpx.AsyncClient(base_url=CONTROL_API_URL, timeout=3.0)


async def get_active_campaign(session_id: str) -> Optional[dict]:
    cached = _cache.get(session_id)
    now = time.monotonic()
    if cached is not None and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    try:
        resp = await _client.get("/campaigns/active", params={"session_id": session_id})
        campaign = resp.json() if resp.status_code == 200 else None
    except httpx.HTTPError as exc:
        print(f"[control_client] failed to fetch active campaign: {exc}")
        campaign = cached[1] if cached is not None else None

    _cache[session_id] = (now, campaign)
    return campaign


async def post_event(event: dict) -> None:
    async def _send() -> None:
        try:
            await _client.post("/events", json=event)
        except httpx.HTTPError as exc:
            print(f"[control_client] failed to post event, falling back to stdout: {exc} -- {event}")

    asyncio.create_task(_send())
