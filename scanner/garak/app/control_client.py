"""Синхронный клиент control-api для scanner-garak. Свой у каждого
сканера по соглашению (общий код между сканерами не выносится)."""
import os
from typing import Optional

import httpx

CONTROL_API_URL = os.environ.get("CONTROL_API_URL", "http://control-api:8000")

_client = httpx.Client(
    base_url=CONTROL_API_URL,
    timeout=30.0,
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


def list_scans(*, status: str, scan_type: str) -> list[dict]:
    resp = _client.get("/scans", params={"status": status, "scan_type": scan_type})
    resp.raise_for_status()
    return resp.json()


def patch_scan(scan_id: int, payload: dict) -> dict:
    resp = _client.patch(f"/scans/{scan_id}", json=payload)
    resp.raise_for_status()
    return resp.json()


def post_log(scan_id: int, message: str, *, level: str = "info", phase: Optional[str] = None) -> None:
    try:
        _client.post(
            f"/scans/{scan_id}/logs",
            json={"level": level, "phase": phase, "message": message},
        )
    except httpx.HTTPError as exc:
        print(f"[scanner-garak] failed to post log for scan {scan_id}: {exc}")


def create_trial(scan_id: int, payload: dict) -> dict:
    resp = _client.post(f"/scans/{scan_id}/trials", json=payload)
    resp.raise_for_status()
    return resp.json()


def patch_trial(trial_id: int, payload: dict) -> dict:
    resp = _client.patch(f"/trials/{trial_id}", json=payload)
    resp.raise_for_status()
    return resp.json()


def list_trial_events(trial_id: int) -> list[dict]:
    """Весь перехваченный трафик прогона (request+response), newest-first по
    API -- используем для поиска канарейки и подсчёта инъекций."""
    resp = _client.get("/events", params={"trial_id": trial_id, "include_body": "true", "limit": 1000})
    resp.raise_for_status()
    return resp.json()


def get_event_detail(event_id: int) -> dict:
    resp = _client.get(f"/events/{event_id}")
    resp.raise_for_status()
    return resp.json()
