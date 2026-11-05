"""Оркестрация одного скана promptfoo red teaming (в фоновом потоке):

    1. Инициализация           -- читает скан и конфиг агента из control-api
    2. Запуск агента           -- launcher собирает и поднимает Pod агента с MITM
    3. Ожидание агента         -- ждёт Running и ответа HTTP-поверхности
    4. Генерация и прогон      -- promptfoo redteam run: генерирует атаки через
                                  LLM_PROVIDER, шлёт их агенту через bridge
    5. Сохранение результатов  -- разбор output.json, остановка агента

Каждый шаг пишет строку ScanLog и фазу. Любая ошибка -> скан failed.
"""
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app import control_client, engine
from app.bridge import AgentBridge

LAUNCHER_URL = os.environ.get("LAUNCHER_URL", "http://launcher:8000")
_BUILD_TIMEOUT = float(os.environ.get("SCAN_BUILD_TIMEOUT", "900"))
_POD_READY_TIMEOUT = float(os.environ.get("SCAN_POD_READY_TIMEOUT", "300"))
_HTTP_READY_TIMEOUT = float(os.environ.get("SCAN_HTTP_READY_TIMEOUT", "120"))

SCAN_TYPE = "promptfoo_redteam"

_running: set[int] = set()
bridge = AgentBridge()


def is_running(scan_id: int) -> bool:
    return scan_id in _running


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(scan_id: int, message: str, *, level: str = "info", phase: str | None = None) -> None:
    control_client.post_log(scan_id, message, level=level, phase=phase)


def _set_phase(scan_id: int, phase: str) -> None:
    control_client.patch_scan(scan_id, {"phase": phase, "status": "running"})
    _log(scan_id, f"Фаза: {phase}", phase=phase)


# --- запуск и ожидание агента (та же логика, что в scanner-indirect) --------

def _target_address(agent_config: dict) -> str | None:
    mode = agent_config.get("interaction_mode")
    if mode == "langgraph":
        return (agent_config.get("langgraph_config") or {}).get("base_url") or None
    if mode == "api":
        return (agent_config.get("api_config") or {}).get("url") or None
    return None


def _wait_pod_ready(scan_id: int, namespace: str) -> None:
    hint = f"; диагностика: kubectl get pods -n {namespace}, kubectl logs -n {namespace} <под> -c agent"
    deadline = time.monotonic() + _POD_READY_TIMEOUT
    last = None
    with httpx.Client(timeout=15.0) as client:
        while time.monotonic() < deadline:
            status = client.get(f"{LAUNCHER_URL}/status/{scan_id}").json()
            current = status.get("status")
            if current != last:
                _log(scan_id, f"Статус пода агента: {current}", phase="Ожидание агента")
                last = current
            if current == "Running":
                return
            if current in ("Failed", "Succeeded"):
                raise RuntimeError(f"под агента завершился со статусом {current}{hint}")
            time.sleep(3)
    raise RuntimeError(f"агент не перешёл в Running за отведённое время{hint}")


def _probe_url(agent_config: dict, address: str) -> str:
    from urllib.parse import urlparse, urlunparse

    if agent_config.get("interaction_mode") == "langgraph":
        return address.rstrip("/") + "/ok"
    parsed = urlparse(address)
    health_path = (agent_config.get("api_config") or {}).get("health_path")
    if health_path:
        path = health_path if health_path.startswith("/") else "/" + health_path
    elif "{{" in parsed.path:
        path = "/"
    else:
        base = parsed.path.rstrip("/")
        if base.endswith("/chat"):
            base = base[: -len("/chat")]
        path = base + "/ok"
    return urlunparse(parsed._replace(path=path, params="", query="", fragment=""))


def _wait_http_ready(scan_id: int, probe: str) -> None:
    deadline = time.monotonic() + _HTTP_READY_TIMEOUT
    with httpx.Client(timeout=5.0) as client:
        while time.monotonic() < deadline:
            try:
                if client.get(probe).status_code < 500:
                    _log(scan_id, f"Агент отвечает на {probe}", phase="Ожидание агента")
                    return
            except httpx.HTTPError:
                pass
            time.sleep(3)
    raise RuntimeError(f"агент не ответил на {probe} за отведённое время")


def _stop_agent(scan_id: int) -> None:
    try:
        with httpx.Client(timeout=30.0) as client:
            client.post(f"{LAUNCHER_URL}/stop/{scan_id}").raise_for_status()
        _log(scan_id, "Агент остановлен, namespace удалён")
    except httpx.HTTPError as exc:
        _log(scan_id, f"Не удалось остановить агента: {exc}", level="error")


# --- точка входа ------------------------------------------------------------

def _parse_config(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _provider_env() -> tuple[str, str, str]:
    base_url = os.environ.get("LLM_PROVIDER_BASE_URL") or ""
    api_key = os.environ.get("LLM_PROVIDER_API_KEY") or ""
    model = os.environ.get("LLM_PROVIDER_MODEL") or ""
    missing = [
        name
        for name, value in [
            ("LLM_PROVIDER_BASE_URL", base_url),
            ("LLM_PROVIDER_API_KEY", api_key),
            ("LLM_PROVIDER_MODEL", model),
        ]
        if not value
    ]
    if missing:
        raise RuntimeError("не заданы переменные окружения: " + ", ".join(missing))
    return base_url, api_key, model


def run_scan(scan_id: int) -> None:
    if scan_id in _running:
        return
    _running.add(scan_id)
    launched = [False]
    try:
        _run(scan_id, launched)
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        if launched[0]:
            _stop_agent(scan_id)
        _log(scan_id, message, level="error", phase="Ошибка")
        control_client.patch_scan(
            scan_id,
            {
                "status": "failed",
                "phase": "Ошибка",
                "error": message,
                "results": json.dumps({"error": message}, ensure_ascii=False),
                "finished_at": _now(),
            },
        )
    finally:
        _running.discard(scan_id)


def _run(scan_id: int, launched: list[bool]) -> None:
    _set_phase(scan_id, "Инициализация")
    scan = control_client.get_scan(scan_id)
    if scan.get("type") != SCAN_TYPE:
        raise RuntimeError(f"scanner-promptfoo-redteam выполняет только сканы типа {SCAN_TYPE}, получен {scan.get('type')}")
    config = _parse_config(scan.get("config"))
    agent_config = control_client.get_agent_config(scan["agent_config_id"])

    plugins = [str(p).strip() for p in (config.get("plugins") or []) if str(p).strip()] or engine.DEFAULT_PLUGINS
    num_tests = max(1, int(config.get("num_tests") or 5))
    language = str(config.get("language") or "").strip() or None
    purpose = str(config.get("purpose") or "").strip() or (agent_config.get("agent_purpose") or "").strip()
    if not purpose:
        raise RuntimeError("не задано назначение агента: заполните agent_purpose в конфиге агента или purpose в конфиге скана")
    max_concurrency = max(1, int(config.get("max_concurrency") or 4))
    provider_base_url, provider_api_key, provider_model = _provider_env()
    engine_version = engine.version()

    _log(scan_id, f"Агент: {agent_config['name']} ({agent_config.get('interaction_mode')})", phase="Инициализация")
    _log(scan_id, f"promptfoo {engine_version}; плагины: {', '.join(plugins)}; тестов на плагин: {num_tests}", phase="Инициализация")

    _set_phase(scan_id, "Запуск агента")
    _log(scan_id, "Сборка и запуск агента через launcher (это может занять несколько минут)...", phase="Запуск агента")
    with httpx.Client(timeout=_BUILD_TIMEOUT) as client:
        resp = client.post(f"{LAUNCHER_URL}/launch", json={"scan_id": scan_id})
        if resp.status_code >= 400:
            raise RuntimeError(f"launcher вернул {resp.status_code}: {resp.text[:500]}")
        launch = resp.json()
    _log(scan_id, f"Агент запущен: pod={launch.get('pod_name')} image={launch.get('built_image')}", level="success", phase="Запуск агента")

    _set_phase(scan_id, "Ожидание агента")
    _wait_pod_ready(scan_id, launch.get("namespace") or "<namespace>")
    agent_config = {**agent_config, **(launch.get("agent_config_patch") or {})}
    address = _target_address(agent_config)
    if not address:
        raise RuntimeError("у агента нет reachable-адреса (задайте api_port в конфиге агента)")
    _log(scan_id, f"Адрес агента: {address}", phase="Ожидание агента")
    _wait_http_ready(scan_id, _probe_url(agent_config, address))
    launched[0] = True

    if engine.WORKDIR.exists():
        shutil.rmtree(engine.WORKDIR)
    engine.WORKDIR.mkdir(parents=True, exist_ok=True)
    engine.write_config(
        engine.WORKDIR,
        provider_base_url=provider_base_url,
        provider_api_key=provider_api_key,
        provider_model=provider_model,
        purpose=purpose,
        plugins=plugins,
        num_tests=num_tests,
        language=language,
        max_concurrency=max_concurrency,
    )

    _set_phase(scan_id, "Генерация и прогон тестов")
    _log(scan_id, "promptfoo генерирует атаки и прогоняет их через агента (обычно несколько минут)...", phase="Генерация и прогон тестов")
    bridge.activate(agent_config)
    started = time.monotonic()
    try:
        out_path = engine.run_redteam(
            scan_id,
            on_log=lambda message, level="info": _log(scan_id, message, level=level, phase="Генерация и прогон тестов"),
        )
    finally:
        bridge.deactivate()
    duration = int(time.monotonic() - started)

    _set_phase(scan_id, "Сохранение результатов")
    payload = engine.build_results(
        out_path,
        meta={
            "engine_version": engine_version,
            "purpose": purpose,
            "plugins": plugins,
            "duration_sec": duration,
        },
    )
    payload["summary"]["bridge"] = bridge.stats()
    s = payload["summary"]
    _log(
        scan_id,
        f"Тестов: {s['tests']}, агент устоял: {s['passed']}, атак прошло: {s['failed']} ({round(s['fail_rate'] * 100)}%)",
        level="success",
        phase="Сохранение результатов",
    )

    _stop_agent(scan_id)
    _log(scan_id, "Сканирование завершено", level="success", phase="Завершено")
    control_client.patch_scan(
        scan_id,
        {"status": "completed", "phase": "Завершено", "results": json.dumps(payload, ensure_ascii=False), "error": None, "finished_at": _now()},
    )


def fail_interrupted_scans() -> None:
    try:
        scans = control_client.list_scans(status="running", scan_type=SCAN_TYPE)
    except httpx.HTTPError as exc:
        print(f"[scanner-promptfoo-redteam] failed to list running scans: {exc}")
        return
    for scan in scans:
        if scan["id"] in _running:
            continue
        message = "Сканирование прервано: сервис scanner-promptfoo-redteam был перезапущен. Создайте сканирование заново"
        try:
            if scan.get("agent_namespace"):
                _stop_agent(scan["id"])
            _log(scan["id"], message, level="error", phase="Ошибка")
            control_client.patch_scan(
                scan["id"],
                {"status": "failed", "phase": "Ошибка", "error": message, "results": json.dumps({"error": message}, ensure_ascii=False), "finished_at": _now()},
            )
        except httpx.HTTPError as exc:
            print(f"[scanner-promptfoo-redteam] failed to mark scan {scan['id']} as failed: {exc}")
