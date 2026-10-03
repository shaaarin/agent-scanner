"""Orchestrates one scan in a background thread:

    1. Инициализация      -- read scan/config/agent/model from control-api
    2. Запуск агента      -- ask launcher to build+launch the tested agent Pod
    3. Ожидание агента    -- poll launcher until the Pod is Running and its
                             HTTP surface answers
    4. Тестирование       -- DeepTeam red-team pass, streaming progress lines
    5. Сохранение         -- write results, mark scan completed

Every step writes a `ScanLog` line (and the current phase) so the scan detail
page can follow along. Any failure is logged and marks the scan failed.
"""
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

import httpx

from app import control_client
from app.deepteam_runner import results_to_payload, run_deepteam

LAUNCHER_URL = os.environ.get("LAUNCHER_URL", "http://launcher:8000")
_BUILD_TIMEOUT = float(os.environ.get("SCAN_BUILD_TIMEOUT", "900"))
_POD_READY_TIMEOUT = float(os.environ.get("SCAN_POD_READY_TIMEOUT", "300"))
_HTTP_READY_TIMEOUT = float(os.environ.get("SCAN_HTTP_READY_TIMEOUT", "120"))

_running: set[int] = set()


class ScanFailed(RuntimeError):
    """Ошибка скана, у которой есть частичный результат (например, таблица
    кейсов, упавших с ошибкой) -- он сохраняется в Scan.results вместе с
    текстом ошибки."""

    def __init__(self, message: str, payload: dict):
        super().__init__(message)
        self.payload = payload


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _errors_summary(errored_rows: list[dict]) -> str:
    """Короткая причина для Scan.error по кейсам с ошибкой."""
    texts = [str(row.get("error") or row.get("reasoning") or "") for row in errored_rows]
    joined = " ".join(texts)
    if any(marker in joined for marker in ("RateLimitError", "insufficient_quota", "429")):
        return (
            "провайдер LLM отклоняет запросы (RateLimitError: превышен лимит запросов "
            "или закончился баланс). Проверьте ключ и лимиты модели-судьи и агента"
        )
    most_common = Counter(texts).most_common(1)[0][0] if texts else "без описания"
    return most_common[:300]


def is_running(scan_id: int) -> bool:
    return scan_id in _running


def _log(scan_id: int, message: str, *, level: str = "info", phase: str | None = None) -> None:
    control_client.post_log(scan_id, message, level=level, phase=phase)


def _set_phase(scan_id: int, phase: str) -> None:
    control_client.patch_scan(scan_id, {"phase": phase, "status": "running"})
    _log(scan_id, f"Фаза: {phase}", phase=phase)


def _target_address(agent_config: dict) -> str | None:
    mode = agent_config.get("interaction_mode")
    if mode == "langgraph":
        return (agent_config.get("langgraph_config") or {}).get("base_url") or None
    if mode == "api":
        return (agent_config.get("api_config") or {}).get("url") or None
    return None


def _wait_pod_ready(scan_id: int) -> None:
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
                raise RuntimeError(f"под агента завершился со статусом {current}")
            time.sleep(3)
    raise RuntimeError("агент не перешёл в Running за отведённое время")


def _probe_url(agent_config: dict, address: str) -> str:
    """Адрес проверки готовности.

    LangGraph -- его `/ok`. REST API -- схема, хост и порт из адреса агента и
    путь: `api_config.health_path`, если задан; иначе прежнее правило --
    путь эндпоинта без "/chat" + "/ok"; если в пути есть плейсхолдер
    (`/ask/{{message}}`), то "/" -- стучаться в шаблонный путь нельзя."""
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
    """The Pod can be Running before the app inside is listening -- poll its
    HTTP surface until it answers (any status below 500 counts)."""
    deadline = time.monotonic() + _HTTP_READY_TIMEOUT
    with httpx.Client(timeout=5.0) as client:
        while time.monotonic() < deadline:
            try:
                resp = client.get(probe)
                if resp.status_code < 500:
                    _log(scan_id, f"Агент отвечает на {probe}", phase="Ожидание агента")
                    return
            except httpx.HTTPError:
                pass
            time.sleep(3)
    raise RuntimeError(f"агент не ответил на {probe} за отведённое время")


def run_scan(scan_id: int) -> None:
    if scan_id in _running:
        return
    _running.add(scan_id)
    try:
        _run(scan_id)
    except Exception as exc:  # noqa: BLE001 -- one scan's failure must not kill the thread pool
        message = str(exc) if isinstance(exc, ScanFailed) else f"{type(exc).__name__}: {exc}"
        payload = {**exc.payload, "error": message} if isinstance(exc, ScanFailed) else {"error": message}
        _log(scan_id, message, level="error", phase="Ошибка")
        control_client.patch_scan(
            scan_id,
            {
                "status": "failed",
                "phase": "Ошибка",
                "error": message,
                "results": json.dumps(payload, ensure_ascii=False),
                "finished_at": _now(),
            },
        )
    finally:
        _running.discard(scan_id)


def _run(scan_id: int) -> None:
    _set_phase(scan_id, "Инициализация")
    scan = control_client.get_scan(scan_id)
    config = json.loads(scan.get("config") or "{}")
    agent_config = control_client.get_agent_config(scan["agent_config_id"])

    vulnerabilities = config.get("vulnerabilities") or ["BFLA", "BOLA", "RBAC"]
    attacks = config.get("attacks") or ["PromptInjection"]
    attacks_per_vulnerability_type = int(config.get("attacks_per_vulnerability_type") or 1)

    eval_llm_model_id = config.get("eval_llm_model_id")
    if not eval_llm_model_id:
        raise RuntimeError("в конфиге скана не задан eval_llm_model_id")
    llm_model = control_client.get_llm_model(eval_llm_model_id)
    _log(scan_id, f"Модель-судья: {llm_model['name']} ({llm_model['model']})", phase="Инициализация")
    _log(scan_id, f"Агент: {agent_config['name']} ({agent_config.get('interaction_mode')})", phase="Инициализация")

    _set_phase(scan_id, "Запуск агента")
    _log(scan_id, "Сборка и запуск агента через launcher (это может занять несколько минут)...", phase="Запуск агента")
    with httpx.Client(timeout=_BUILD_TIMEOUT) as client:
        resp = client.post(f"{LAUNCHER_URL}/launch", json={"scan_id": scan_id})
        if resp.status_code >= 400:
            raise RuntimeError(f"launcher вернул {resp.status_code}: {resp.text[:500]}")
        launch = resp.json()
    _log(
        scan_id,
        f"Агент запущен: pod={launch.get('pod_name')} image={launch.get('built_image')}",
        level="success",
        phase="Запуск агента",
    )

    _set_phase(scan_id, "Ожидание агента")
    _wait_pod_ready(scan_id)

    # launcher may have patched the agent's reachable address into its config.
    agent_config = control_client.get_agent_config(scan["agent_config_id"])
    address = _target_address(agent_config)
    if not address:
        raise RuntimeError(
            "у агента нет reachable-адреса (задайте api_port в конфиге агента, чтобы launcher пробросил NodePort)"
        )
    _log(scan_id, f"Адрес агента: {address}", phase="Ожидание агента")
    _wait_http_ready(scan_id, _probe_url(agent_config, address))

    _set_phase(scan_id, "Тестирование")
    _log(scan_id, "Запуск DeepTeam red teaming...", phase="Тестирование")
    results = run_deepteam(
        agent_config=agent_config,
        llm_model=llm_model,
        vulnerabilities=vulnerabilities,
        attacks=attacks,
        attacks_per_vulnerability_type=attacks_per_vulnerability_type,
        session_id=scan["session_id"],
        on_log=lambda level, message: _log(scan_id, message, level=level, phase="Тестирование"),
    )

    _set_phase(scan_id, "Сохранение результатов")
    payload = results_to_payload(results)
    rows = payload["vulnerability_results"]
    errored = [row for row in rows if row["errored"]]
    valid = [row for row in rows if not row["errored"]]
    passed = sum(1 for row in valid if row["passed"])

    # Кейс с ошибкой (атаку не удалось сгенерировать, агент не ответил,
    # судья недоступен) -- это не результат теста. Если не оценён ни один
    # кейс, скан провален, а не «завершён с 0 пройденных».
    if not rows:
        raise RuntimeError("DeepTeam не сгенерировал ни одного тест-кейса")
    if not valid:
        raise ScanFailed(
            f"Ни один из {len(rows)} кейсов не удалось проверить: {_errors_summary(errored)}",
            payload,
        )

    _log(
        scan_id,
        f"Кейсов: {len(rows)}, оценено: {len(valid)}, пройдено: {passed}, с ошибкой: {len(errored)}",
        level="success",
        phase="Сохранение результатов",
    )
    if errored:
        _log(
            scan_id,
            f"Внимание: {len(errored)} из {len(rows)} кейсов завершились ошибкой и не учтены в оценке: "
            f"{_errors_summary(errored)}",
            level="error",
            phase="Сохранение результатов",
        )

    control_client.patch_scan(
        scan_id,
        {
            "status": "completed",
            "phase": "Завершено",
            "results": json.dumps(payload),
            "error": None,
            "finished_at": _now(),
        },
    )
    _log(scan_id, "Сканирование завершено", level="success", phase="Завершено")
