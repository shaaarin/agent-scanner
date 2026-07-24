import os

import httpx

CONTROL_API_URL = os.environ.get("CONTROL_API_URL", "http://control-api:8000")

_client = httpx.Client(base_url=CONTROL_API_URL, timeout=10.0)


def get_campaign(campaign_id: int) -> dict:
    resp = _client.get(f"/campaigns/{campaign_id}")
    resp.raise_for_status()
    return resp.json()


def get_agent_config(agent_config_id: int) -> dict:
    resp = _client.get(f"/agent-configs/{agent_config_id}")
    resp.raise_for_status()
    return resp.json()


def update_campaign(campaign_id: int, payload: dict) -> dict:
    resp = _client.patch(f"/campaigns/{campaign_id}", json=payload)
    resp.raise_for_status()
    return resp.json()


def update_agent_config(agent_config_id: int, payload: dict) -> dict:
    resp = _client.put(f"/agent-configs/{agent_config_id}", json=payload)
    resp.raise_for_status()
    return resp.json()
