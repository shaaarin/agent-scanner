"""Один скан типа `ai_code_scan` в фоновом потоке:

    1. Инициализация           -- скан, конфиг агента, параметры, версия semgrep
    2. Клонирование            -- shallow-clone ветки агента
    3. Анализ кода             -- локальный semgrep scan --json
    4. Сохранение результатов  -- Scan.results, статус completed

Оркестрация -- как в scanner-promptfoo: каждый шаг пишет ScanLog и фазу,
любая ошибка переводит скан в failed с текстом в Scan.error. Агент не
собирается и не запускается, код репозитория никуда не отправляется --
kind, launcher и внешние сервисы здесь не нужны.
"""
import json
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

from app import control_client, repo, semgrep

SCAN_TYPE = "ai_code_scan"
BASE_RULES = "/srv/rules/ai-security.yml"
DEFAULT_MIN_SEVERITY = "low"
MAX_CUSTOM_RULES_LENGTH = 20000

# Дополнительные официальные наборы Semgrep Registry (значение = --config p/...).
# Загружаются из интернета при скане; базовый AI-набор выполняется всегда.
RULE_SETS = {
    "p/owasp-top-ten": {
        "label": "OWASP Top 10",
        "description": "Официальный набор Semgrep Registry по OWASP Top 10 (загружается из интернета при скане)",
    },
    "p/secrets": {
        "label": "Секреты в коде",
        "description": "Официальный набор Semgrep Registry: жёстко зашитые токены и пароли (загружается из интернета)",
    },
    "p/security-audit": {
        "label": "Общий аудит безопасности",
        "description": "Широкий официальный набор Semgrep Registry по известным антипаттернам (загружается из интернета)",
    },
}

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
        # RuntimeError (и RepoError/SemgrepError) -- наши понятные сообщения;
        # остальное (сеть, control-api) -- с типом исключения для диагностики.
        message = str(exc) if isinstance(exc, RuntimeError) else f"{type(exc).__name__}: {exc}"
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


def fail_interrupted_scans() -> None:
    """При старте сервиса: скан ai_code_scan в статусе running, который не
    выполняется в этом процессе, прервался вместе с прошлым запуском сканера
    и иначе навсегда остался бы «Выполняется»."""
    try:
        scans = control_client.list_scans(status="running", scan_type=SCAN_TYPE)
    except httpx.HTTPError as exc:
        print(f"[scanner-semgrep] failed to list running scans: {exc}")
        return
    for scan in scans:
        if scan["id"] in _running:
            continue
        message = "Анализ прерван: сервис scanner-semgrep был перезапущен. Создайте сканирование заново"
        try:
            _log(scan["id"], message, level="error", phase="Ошибка")
            control_client.patch_scan(
                scan["id"],
                {
                    "status": "failed",
                    "phase": "Ошибка",
                    "error": message,
                    "results": json.dumps({"error": message}, ensure_ascii=False),
                    "finished_at": _now(),
                },
            )
        except httpx.HTTPError as exc:
            print(f"[scanner-semgrep] failed to mark scan {scan['id']} as failed: {exc}")


def _validate_custom_rules(text: str) -> None:
    if len(text) > MAX_CUSTOM_RULES_LENGTH:
        raise RuntimeError(f"пользовательские правила длиннее {MAX_CUSTOM_RULES_LENGTH} символов")
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RuntimeError(f"пользовательские правила -- некорректный YAML: {str(exc)[:300]}") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("rules"), list) or not parsed["rules"]:
        raise RuntimeError('пользовательские правила: ожидается YAML-объект с непустым списком "rules"')
    for index, rule in enumerate(parsed["rules"]):
        if not isinstance(rule, dict) or not rule.get("id"):
            raise RuntimeError(f"пользовательские правила: правило #{index + 1} без поля id")


def _run(scan_id: int) -> None:
    _set_phase(scan_id, "Инициализация")
    scan = control_client.get_scan(scan_id)
    if scan.get("type") != SCAN_TYPE:
        raise RuntimeError(f"scanner-semgrep выполняет только сканы типа {SCAN_TYPE}, получен {scan.get('type')}")
    config = _parse_config(scan.get("config"))
    agent_config = control_client.get_agent_config(scan["agent_config_id"])

    min_severity = str(config.get("min_severity") or DEFAULT_MIN_SEVERITY).lower()
    if min_severity not in semgrep.SEVERITIES:
        raise RuntimeError(
            f"недопустимый min_severity={min_severity!r}, ожидается одно из: {', '.join(semgrep.SEVERITIES)}"
        )
    rule_sets = [str(value) for value in (config.get("rule_sets") or [])]
    unknown = [value for value in rule_sets if value not in RULE_SETS]
    if unknown:
        raise RuntimeError(f"неизвестные наборы правил: {', '.join(unknown)}")
    custom_rules = str(config.get("custom_rules") or "").strip() or None
    if custom_rules:
        _validate_custom_rules(custom_rules)

    engine_version = semgrep.version()
    _log(scan_id, f"Агент: {agent_config['name']}", phase="Инициализация")
    _log(scan_id, f"Репозиторий: {agent_config['git_repo_url']} (ветка {agent_config['git_ref']})", phase="Инициализация")
    extras = ", ".join(RULE_SETS[value]["label"] for value in rule_sets)
    _log(
        scan_id,
        f"semgrep {engine_version}, базовый AI-набор{'; дополнительно: ' + extras if extras else ''}"
        f"{'; пользовательские правила' if custom_rules else ''}"
        f", минимальная критичность: {min_severity}",
        phase="Инициализация",
    )

    workdir = Path(tempfile.mkdtemp(prefix=f"ai-code-scan-{scan_id}-"))
    try:
        _set_phase(scan_id, "Клонирование")
        repo_path = workdir / "repo"
        commit = repo.clone(
            agent_config["git_repo_url"],
            agent_config["git_ref"],
            agent_config.get("git_access_token"),
            repo_path,
        )
        _log(scan_id, f"Коммит {commit[:12]}", level="success", phase="Клонирование")

        _set_phase(scan_id, "Анализ кода")
        rule_configs = [BASE_RULES, *rule_sets]
        if custom_rules:
            custom_path = workdir / "custom-rules.yml"
            custom_path.write_text(custom_rules, encoding="utf-8")
            rule_configs.append(str(custom_path))
        started_at = time.monotonic()
        report = semgrep.run_scan(
            repo_path,
            rule_configs,
            on_log=lambda level, message: _log(scan_id, message, level=level, phase="Анализ кода"),
        )
        duration = int(time.monotonic() - started_at)

        _set_phase(scan_id, "Сохранение результатов")
        scanned = len((report.get("paths") or {}).get("scanned") or [])
        payload = semgrep.build_results(
            report,
            meta={
                "engine_label": "semgrep",
                "engine_version": engine_version,
                "git_ref": agent_config["git_ref"],
                "commit": commit,
                "min_severity": min_severity,
                "rule_sets": rule_sets,
                "custom_rules": bool(custom_rules),
                "duration_sec": duration,
            },
            coverage=(
                f"Локальный semgrep {engine_version}: AST-правила одного файла "
                f"({len(rule_configs)} конфиг(ов) правил), просканировано файлов: {scanned}. "
                "Нет межфайлового taint; находка -- повод проверить код, "
                "отсутствие находок не доказывает безопасность."
            ),
            min_severity=min_severity,
        )
        summary = payload["summary"]

        _log(
            scan_id,
            "Найдено проблем: {total} (высоких {high}, средних {medium}, низких {low})".format(**summary),
            level="success",
            phase="Сохранение результатов",
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    # Последняя строка журнала -- до смены статуса: страница скана перестаёт
    # опрашивать журнал, как только видит completed.
    _log(scan_id, "Анализ AI-кода завершён", level="success", phase="Завершено")
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
