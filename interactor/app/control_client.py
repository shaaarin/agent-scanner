import os

import httpx

CONTROL_API_URL = os.environ.get("CONTROL_API_URL", "http://control-api:8000")

_client = httpx.AsyncClient(base_url=CONTROL_API_URL, timeout=10.0)


async def get_campaign(campaign_id: int) -> dict:
    resp = await _client.get(f"/campaigns/{campaign_id}")
    resp.raise_for_status()
    return resp.json()


async def get_agent_config(agent_config_id: int) -> dict:
    resp = await _client.get(f"/agent-configs/{agent_config_id}")
    resp.raise_for_status()
    return resp.json()


async def get_llm_model(llm_model_id: int) -> dict:
    resp = await _client.get(f"/llm-models/{llm_model_id}")
    resp.raise_for_status()
    return resp.json()


async def get_template(template_id: int) -> dict:
    resp = await _client.get(f"/templates/{template_id}")
    resp.raise_for_status()
    return resp.json()


async def has_success(session_id: str) -> bool:
    resp = await _client.get("/events", params={"session_id": session_id, "success_detected": True, "limit": 1})
    resp.raise_for_status()
    return len(resp.json()) > 0
