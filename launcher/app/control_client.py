import os

import httpx

CONTROL_API_URL = os.environ.get("CONTROL_API_URL", "http://control-api:8000")

_client = httpx.Client(
    base_url=CONTROL_API_URL,
    timeout=10.0,
    # Машинный контур: общий секрет сервисов платформы (control-api
    # принимает запросы только с валидным X-Internal-Token или сессией).
    headers={"X-Internal-Token": os.environ.get("INTERNAL_API_TOKEN", "")},
)


def get_scan(scan_id: int) -> dict:
    resp = _client.get(f"/scans/{scan_id}")
    resp.raise_for_status()
    return resp.json()


def get_agent_config(agent_config_id: int) -> dict:
    resp = _client.get(f"/agent-configs/{agent_config_id}")
    resp.raise_for_status()
    return resp.json()


def update_scan(scan_id: int, payload: dict) -> dict:
    resp = _client.patch(f"/scans/{scan_id}", json=payload)
    resp.raise_for_status()
    return resp.json()


def update_agent_config(agent_config_id: int, payload: dict) -> dict:
    resp = _client.put(f"/agent-configs/{agent_config_id}", json=payload)
    resp.raise_for_status()
    return resp.json()
