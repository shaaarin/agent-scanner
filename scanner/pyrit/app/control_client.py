"""Thin synchronous client for control-api, used by the scanner's background
thread (the whole PyRIT run is synchronous from the thread's perspective, so
there's no reason to make these async)."""
import os

import httpx

CONTROL_API_URL = os.environ.get("CONTROL_API_URL", "http://control-api:8000")

_client = httpx.Client(base_url=CONTROL_API_URL, timeout=30.0)


def get_scan(scan_id: int) -> dict:
    resp = _client.get(f"/scans/{scan_id}")
    resp.raise_for_status()
    return resp.json()


def get_agent_config(agent_config_id: int) -> dict:
    resp = _client.get(f"/agent-configs/{agent_config_id}")
    resp.raise_for_status()
    return resp.json()


def get_llm_model(llm_model_id: int) -> dict:
    resp = _client.get(f"/llm-models/{llm_model_id}")
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


def post_log(scan_id: int, message: str, *, level: str = "info", phase: str | None = None) -> None:
    try:
        _client.post(
            f"/scans/{scan_id}/logs",
            json={"level": level, "phase": phase, "message": message},
        )
    except httpx.HTTPError as exc:
        # Never let logging take down the scan itself.
        print(f"[scanner] failed to post log for scan {scan_id}: {exc}")
