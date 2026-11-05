"""Один скан типа `agent_skills` в фоновом потоке:

    0. В очереди               -- если уже идут SCAN_MAX_CONCURRENT сканов (D-27)
    1. Инициализация           -- скан, проверка конфига: движки, источник (D-46)
    2. Получение исходников    -- zip или git, распаковка, поиск скиллов (sources);
                                  архив с признаками атаки -- сразу к п. 4, block
    3. Статический анализ      -- движки по каждому скиллу (stages)
    4. Сохранение результатов  -- Scan.results, статус completed

Оркестрация -- как в scanner-semgrep: каждый шаг пишет ScanLog и фазу, любая
ошибка переводит скан в failed с текстом в Scan.error. На весь скан --
дедлайн SCAN_TOTAL_TIMEOUT (отсчёт с выхода из очереди), на запуск движка --
SCAN_ENGINE_TIMEOUT (D-33). Скиллы не запускаются, kind/launcher не нужны.
"""
import json
import os
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app import control_client, report, stages
from app.context import Deadline, ScanContext

SCAN_TYPE = "agent_skills"
ENGINES = {
    "cisco": {"label": "Cisco skill-scanner", "description": "Cisco AI Defense skill-scanner 2.1.0: статика, поведенческий анализ скриптов, YARA"},
    "skillspector": {"label": "NVIDIA SkillSpector", "description": "NVIDIA SkillSpector 2.11.2 без LLM: статические правила, YARA, проверка зависимостей (OSV.dev)"},
}
DEFAULT_ENGINES = list(ENGINES)
SOURCE_KINDS = ("zip", "repository")


def _env_number(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except ValueError:
        return default
    return value if value > 0 else default


MAX_CONCURRENT = int(_env_number("SCAN_MAX_CONCURRENT", 2))
ENGINE_TIMEOUT = _env_number("SCAN_ENGINE_TIMEOUT", 300)
TOTAL_TIMEOUT = _env_number("SCAN_TOTAL_TIMEOUT", 1800)
MAX_SKILLS = int(_env_number("SCAN_MAX_SKILLS", 50))

_slots = threading.BoundedSemaphore(MAX_CONCURRENT)
_running: set[int] = set()
_running_lock = threading.Lock()


def is_running(scan_id: int) -> bool:
    with _running_lock:
        return scan_id in _running


def _claim(scan_id: int) -> bool:
    """Атомарно помечает скан выполняемым; False -- уже выполняется."""
    with _running_lock:
        if scan_id in _running:
            return False
        _running.add(scan_id)
        return True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(scan_id: int, message: str, *, level: str = "info", phase: str | None = None) -> None:
    control_client.post_log(scan_id, message, level=level, phase=phase)


def _set_phase(scan_id: int, phase: str) -> None:
    control_client.patch_scan(scan_id, {"phase": phase, "status": "running"})
    _log(scan_id, f"Фаза: {phase}", phase=phase)


def _fail(scan_id: int, message: str) -> None:
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


def _parse_config(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"конфиг скана не является JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("конфиг скана должен быть JSON-объектом")
    return value


def parse_engines(config: dict) -> list[str]:
    """Движки из формы; пусто/не задано -- оба (D-16). Порядок -- как в
    ENGINES, дубли убираются, незнакомые -- ошибка."""
    raw = config.get("engines")
    if raw in (None, "", []):
        return list(DEFAULT_ENGINES)
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise RuntimeError("поле engines должно быть списком движков")
    requested = {str(value) for value in raw}
    unknown = sorted(requested - set(ENGINES))
    if unknown:
        raise RuntimeError(f"неизвестные движки: {', '.join(unknown)}; доступны: {', '.join(ENGINES)}")
    return [engine for engine in ENGINES if engine in requested]


def parse_source(config: dict) -> dict:
    """Снимок источника, который control-api кладёт в Scan.config (D-46)."""
    source = config.get("source")
    if not isinstance(source, dict) or source.get("kind") not in SOURCE_KINDS:
        raise RuntimeError("в конфиге скана нет источника скиллов -- создайте сканирование заново из карточки актива")
    if source["kind"] == "zip" and not (source.get("asset_id") and source.get("archive_sha256")):
        raise RuntimeError("источник zip без asset_id/archive_sha256 -- создайте сканирование заново из карточки актива")
    if source["kind"] == "repository" and not str(source.get("git_repo_url") or "").strip():
        raise RuntimeError("источник repository без git_repo_url -- создайте сканирование заново из карточки актива")
    return source


def describe_source(source: dict) -> str:
    """Источник для журнала -- без токена."""
    if source["kind"] == "zip":
        name = source.get("archive_filename") or "без имени"
        return f"zip-архив {name} (sha256 {str(source['archive_sha256'])[:12]}…)"
    return f"репозиторий {source['git_repo_url']} (ветка/коммит {source.get('git_ref') or 'main'})"


def run_scan(scan_id: int) -> None:
    """Синхронный запуск (поток уже свой). Повторный вызов для
    выполняющегося скана ничего не делает."""
    if _claim(scan_id):
        _run_claimed(scan_id)


def _run_claimed(scan_id: int) -> None:
    acquired = False
    try:
        if not _slots.acquire(blocking=False):
            control_client.patch_scan(scan_id, {"phase": "В очереди", "status": "running"})
            _log(
                scan_id,
                f"Все слоты заняты (одновременно не больше {MAX_CONCURRENT} сканов) -- ждём своей очереди",
                phase="В очереди",
            )
            _slots.acquire()
        acquired = True
        _run(scan_id)
    except Exception as exc:  # noqa: BLE001 -- падение одного скана не должно ронять поток
        # RuntimeError (в т.ч. ScanTimeout) -- наши понятные
        # сообщения; остальное (сеть, control-api) -- с типом для диагностики.
        message = str(exc) if isinstance(exc, RuntimeError) else f"{type(exc).__name__}: {exc}"
        try:
            _fail(scan_id, message)
        except httpx.HTTPError as report_exc:
            print(f"[scanner-skills] failed to mark scan {scan_id} as failed: {report_exc}")
    finally:
        if acquired:
            _slots.release()
        with _running_lock:
            _running.discard(scan_id)


def start_in_background(scan_id: int) -> bool:
    """Запускает скан в своём потоке (ожидание очереди не занимает пул
    asyncio). False -- скан уже выполняется."""
    if not _claim(scan_id):
        return False
    threading.Thread(target=_run_claimed, args=(scan_id,), name=f"skills-scan-{scan_id}", daemon=True).start()
    return True


def fail_interrupted_scans() -> None:
    """При старте сервиса: скан agent_skills в статусе running, который не
    выполняется в этом процессе, прервался вместе с прошлым запуском сканера
    и иначе навсегда остался бы «Выполняется»."""
    try:
        scans = control_client.list_scans(status="running", scan_type=SCAN_TYPE)
    except httpx.HTTPError as exc:
        print(f"[scanner-skills] failed to list running scans: {exc}")
        return
    for scan in scans:
        if is_running(scan["id"]):
            continue
        try:
            _fail(scan["id"], "Анализ прерван: сервис scanner-skills был перезапущен. Запустите сканирование заново")
        except httpx.HTTPError as exc:
            print(f"[scanner-skills] failed to mark scan {scan['id']} as failed: {exc}")


def _run(scan_id: int) -> None:
    deadline = Deadline(TOTAL_TIMEOUT)
    _set_phase(scan_id, "Инициализация")
    scan = control_client.get_scan(scan_id)
    if scan.get("type") != SCAN_TYPE:
        raise RuntimeError(f"scanner-skills выполняет только сканы типа {SCAN_TYPE}, получен {scan.get('type')}")
    if scan.get("asset_kind") not in (None, "skill"):
        raise RuntimeError(f"скан ссылается на актив «{scan.get('asset_kind')}», а не на skill")
    config = _parse_config(scan.get("config"))
    engines = parse_engines(config)
    source = parse_source(config)

    _log(scan_id, f"Источник: {describe_source(source)}", phase="Инициализация")
    _log(scan_id, f"Движки: {', '.join(ENGINES[e]['label'] for e in engines)}", phase="Инициализация")
    _log(
        scan_id,
        f"Таймауты: {ENGINE_TIMEOUT:.0f} с на запуск движка, {TOTAL_TIMEOUT:.0f} с на весь скан; не больше {MAX_SKILLS} скиллов",
        phase="Инициализация",
    )
    if config.get("eval_llm_model_id"):
        _log(scan_id, "LLM-анализ отключён в этой версии: выполняется только статический анализ", phase="Инициализация")

    workdir = Path(tempfile.mkdtemp(prefix=f"skills-scan-{scan_id}-"))
    try:
        ctx = ScanContext(
            scan_id=scan_id,
            scan=scan,
            config=config,
            engines=engines,
            source=source,
            workdir=workdir,
            deadline=deadline,
            engine_timeout=ENGINE_TIMEOUT,
            max_skills=MAX_SKILLS,
            log=lambda message, **kw: _log(scan_id, message, **kw),
        )

        _set_phase(scan_id, "Получение исходников")
        stages.fetch_sources(ctx)
        deadline.check()

        if ctx.rejected:
            # Признак атаки в архиве: движки не запускаем, результат -- block (D-21).
            _set_phase(scan_id, "Сохранение результатов")
            payload = report.rejected_results(ctx)
            final_message = f"Архив отклонён, вердикт block: {ctx.rejected['detail']}"
        else:
            _set_phase(scan_id, "Статический анализ")
            stages.analyze(ctx)
            deadline.check()

            _set_phase(scan_id, "Сохранение результатов")
            payload = stages.build_results(ctx)
            final_message = report.final_message(payload)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    # Последняя строка журнала -- до смены статуса: страница скана перестаёт
    # опрашивать журнал, как только видит completed.
    _log(scan_id, final_message, level="success", phase="Завершено")
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
