"""Синхронный клиент к control-api. Своя копия по образцу
`scanner/semgrep/app/control_client.py` -- общий код между сканерами не
выносится, у каждого свой."""
import os

import httpx

CONTROL_API_URL = os.environ.get("CONTROL_API_URL", "http://control-api:8000")

_client = httpx.Client(base_url=CONTROL_API_URL, timeout=30.0)


def get_scan(scan_id: int) -> dict:
    resp = _client.get(f"/scans/{scan_id}")
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
    # Уровни журнала control-api: info | success | error (ScanLogLevel).
    try:
        resp = _client.post(
            f"/scans/{scan_id}/logs",
            json={"level": level, "phase": phase, "message": message},
        )
        if resp.is_error:
            print(f"[scanner-skills] control-api rejected log for scan {scan_id}: {resp.status_code} {resp.text[:200]}")
    except httpx.HTTPError as exc:
        # Журнал не должен ронять сам скан.
        print(f"[scanner-skills] failed to post log for scan {scan_id}: {exc}")
