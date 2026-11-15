"""Синхронный клиент к control-api. Своя копия по образцу
`scanner/semgrep/app/control_client.py` -- общий код между сканерами не
выносится, у каждого свой."""
import hashlib
import os
from pathlib import Path

import httpx

CONTROL_API_URL = os.environ.get("CONTROL_API_URL", "http://control-api:8000")

_client = httpx.Client(
    base_url=CONTROL_API_URL,
    timeout=30.0,
    # Машинный контур: общий секрет сервисов платформы (control-api
    # принимает запросы только с валидным X-Internal-Token или сессией).
    headers={"X-Internal-Token": os.environ.get("INTERNAL_API_TOKEN", "")},
)


def get_scan(scan_id: int, *, wait_for_dispatch: bool = False) -> dict:
    params = {"wait_for_dispatch": "true"} if wait_for_dispatch else {}
    resp = _client.get(f"/scans/{scan_id}", params=params)
    resp.raise_for_status()
    return resp.json()


def list_scans(*, status: str, scan_type: str) -> list[dict]:
    resp = _client.get("/scans", params={"status": status, "scan_type": scan_type})
    resp.raise_for_status()
    return resp.json()


def download_skill_archive(asset_id: int, dest: Path, *, max_bytes: int) -> tuple[str, int]:
    """Скачивает zip skill-актива (`GET /skill-assets/{id}/content`) потоком в
    `dest`, не больше `max_bytes`. Возвращает (sha256, размер)."""
    digest = hashlib.sha256()
    size = 0
    with _client.stream("GET", f"/skill-assets/{asset_id}/content", timeout=120.0) as resp:
        if resp.status_code == 404:
            raise RuntimeError("архив skill-актива не найден в control-api (актив удалён?)")
        resp.raise_for_status()
        with dest.open("wb") as out:
            for chunk in resp.iter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise RuntimeError(f"архив больше {max_bytes // (1024 * 1024)} МиБ")
                digest.update(chunk)
                out.write(chunk)
    return digest.hexdigest(), size


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
