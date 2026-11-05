"""MCP control-api client with bounded retries for transient failures.

Only control-plane requests are retried, never worker /execute calls.
Log delivery is best effort with possible duplicates: a lost POST response can
cause a duplicate line. There is no durable queue.
"""
import logging
import os
import time

import httpx

CONTROL_API_URL = os.environ.get("CONTROL_API_URL", "http://control-api:8000")

_client = httpx.Client(
    base_url=CONTROL_API_URL,
    timeout=30.0,
    # Машинный контур: общий секрет сервисов платформы (control-api
    # принимает запросы только с валидным X-Internal-Token или сессией).
    headers={"X-Internal-Token": os.environ.get("INTERNAL_API_TOKEN", "")},
)
logger = logging.getLogger(__name__)
ATTEMPTS = 5
REQUEST_TIMEOUT = httpx.Timeout(5.0, connect=2.0)


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    for attempt in range(ATTEMPTS):
        try:
            response = _client.request(method, path, timeout=REQUEST_TIMEOUT, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            # Invalid/deleted scans and validation errors won't heal on retry.
            if exc.response.status_code != 429 and exc.response.status_code < 500:
                raise
            failure = f"HTTP {exc.response.status_code}"
            if attempt == ATTEMPTS - 1:
                raise
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            failure = type(exc).__name__
            if attempt == ATTEMPTS - 1:
                raise
        delay = 2 ** attempt  # 1, 2, 4, 8 seconds; finite per request
        # Never print request/response bodies (scan configs can contain secrets).
        logger.warning("control-api %s %s: %s; retry %s/%s in %ss",
                       method, path, failure, attempt + 2, ATTEMPTS, delay)
        time.sleep(delay)
    raise AssertionError("Unreachable")


def get_scan(scan_id: int) -> dict:
    resp = _request("GET", f"/scans/{scan_id}")
    return resp.json()


def get_agent_config(agent_config_id: int) -> dict:
    resp = _request("GET", f"/agent-configs/{agent_config_id}")
    return resp.json()


def list_scans(*, status: str, scan_type: str) -> list[dict]:
    resp = _request("GET", "/scans", params={"status": status, "scan_type": scan_type})
    return resp.json()


def patch_scan(scan_id: int, payload: dict) -> dict:
    resp = _request("PATCH", f"/scans/{scan_id}", json=payload)
    return resp.json()


def post_log(scan_id: int, message: str, *, level: str = "info", phase: str | None = None) -> bool:
    try:
        _request(
            "POST", f"/scans/{scan_id}/logs",
            json={"level": level, "phase": phase, "message": message},
        )
        return True
    except httpx.HTTPError as exc:
        # Журнал не должен ронять сам скан.
        logger.error("MCP scan %s: log delivery failed (%s); line not persisted",
                     scan_id, type(exc).__name__)
        return False
