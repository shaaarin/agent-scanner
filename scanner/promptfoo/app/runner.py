"""Один скан типа `code_scan` в фоновом потоке:

    1. Инициализация           -- скан, конфиг агента, параметры, ключ Promptfoo
    2. Клонирование            -- shallow-clone ветки агента + служебные коммиты
    3. Анализ кода             -- promptfoo code-scans run --json
    4. Сохранение результатов  -- Scan.results, статус completed

Как и в scanner-deepteam: каждый шаг пишет ScanLog и фазу, любая ошибка
переводит скан в failed с текстом в Scan.error. Агент не собирается и не
запускается -- kind и launcher здесь не нужны.
"""
import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from app import control_client, promptfoo, repo

SCAN_TYPE = "code_scan"
DEFAULT_MIN_SEVERITY = "medium"
MAX_GUIDANCE_LENGTH = 4000

_running: set[int] = set()


def is_running(scan_id: int) -> bool:
    return scan_id in _running


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(scan_id: int, message: str, *, level: str = "info", phase: str | None = None) -> None:
    control_client.post_log(scan_id, message, level=level, phase=phase)


def _set_phase(scan_id: int, phase: str) -> None:
    control_client.patch_scan(scan_id, {"phase": phase, "status": "running"})
    _log(scan_id, f"Фаза: {phase}", phase=phase)


def _parse_config(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"конфиг скана не является JSON: {exc}") from exc
    return value if isinstance(value, dict) else {}


def run_scan(scan_id: int) -> None:
    if scan_id in _running:
        return
    _running.add(scan_id)
    try:
        _run(scan_id)
    except Exception as exc:  # noqa: BLE001 -- падение одного скана не должно ронять поток
        # RuntimeError (и RepoError/PromptfooError) -- наши понятные сообщения;
        # остальное (сеть, control-api) -- с типом исключения для диагностики.
        message = str(exc) if isinstance(exc, RuntimeError) else f"{type(exc).__name__}: {exc}"
        _log(scan_id, message, level="error", phase="Ошибка")
        control_client.patch_scan(
            scan_id,
            {
                "status": "failed",
                "phase": "Ошибка",
                "error": message,
                "results": json.dumps({"error": message}),
                "finished_at": _now(),
            },
        )
    finally:
        _running.discard(scan_id)


def _run(scan_id: int) -> None:
    _set_phase(scan_id, "Инициализация")
    scan = control_client.get_scan(scan_id)
    if scan.get("type") != SCAN_TYPE:
        raise RuntimeError(f"scanner-promptfoo выполняет только сканы типа {SCAN_TYPE}, получен {scan.get('type')}")
    config = _parse_config(scan.get("config"))
    agent_config = control_client.get_agent_config(scan["agent_config_id"])

    min_severity = str(config.get("min_severity") or DEFAULT_MIN_SEVERITY).lower()
    if min_severity not in promptfoo.SEVERITIES:
        raise RuntimeError(f"недопустимый min_severity={min_severity!r}, ожидается одно из: {', '.join(promptfoo.SEVERITIES)}")
    guidance = str(config.get("guidance") or "").strip() or None
    if guidance and len(guidance) > MAX_GUIDANCE_LENGTH:
        raise RuntimeError(f"дополнительные инструкции длиннее {MAX_GUIDANCE_LENGTH} символов")

    if not os.environ.get("PROMPTFOO_API_KEY"):
        raise RuntimeError("не задан PROMPTFOO_API_KEY: добавьте ключ Promptfoo в .env и пересоздайте scanner-promptfoo")

    engine_version = promptfoo.version()
    _log(scan_id, f"Агент: {agent_config['name']}", phase="Инициализация")
    _log(scan_id, f"Репозиторий: {agent_config['git_repo_url']} (ветка {agent_config['git_ref']})", phase="Инициализация")
    _log(scan_id, f"promptfoo {engine_version}, минимальная серьёзность: {min_severity}", phase="Инициализация")

    workdir = Path(tempfile.mkdtemp(prefix=f"code-scan-{scan_id}-"))
    try:
        _set_phase(scan_id, "Клонирование")
        repo_path = workdir / "repo"
        repo.clone(agent_config["git_repo_url"], agent_config["git_ref"], agent_config.get("git_access_token"), repo_path)
        prepared = repo.prepare(repo_path)
        _log(
            scan_id,
            f"Коммит {prepared.commit[:12]}, файлов к анализу: {prepared.files}",
            level="success",
            phase="Клонирование",
        )

        _set_phase(scan_id, "Анализ кода")
        _log(scan_id, "Запуск анализа в Promptfoo, обычно он занимает от 3 до 20 минут...", phase="Анализ кода")
        started = time.monotonic()
        response = promptfoo.run_code_scan(
            prepared.path,
            prepared.base,
            prepared.compare,
            min_severity=min_severity,
            guidance=guidance,
            on_log=lambda level, message: _log(scan_id, message, level=level, phase="Анализ кода"),
        )
        duration = int(time.monotonic() - started)

        _set_phase(scan_id, "Сохранение результатов")
        payload = promptfoo.build_results(
            response,
            meta={
                "engine_version": engine_version,
                "git_ref": agent_config["git_ref"],
                "commit": prepared.commit,
                "files_in_scope": prepared.files,
                "min_severity": min_severity,
                "duration_sec": duration,
            },
        )
        summary = payload["summary"]
        _log(
            scan_id,
            "Найдено проблем: {total} (критических {critical}, высоких {high}, средних {medium}, низких {low})".format(**summary),
            level="success",
            phase="Сохранение результатов",
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    control_client.patch_scan(
        scan_id,
        {
            "status": "completed",
            "phase": "Завершено",
            "results": json.dumps(payload, ensure_ascii=False),
            "error": None,
            "finished_at": _now(),
        },
    )
    _log(scan_id, "Анализ кода завершён", level="success", phase="Завершено")
