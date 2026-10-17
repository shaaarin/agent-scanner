import asyncio
import json
import logging
import os
import re
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from app.config import validate_flat
from app import control_client as control
from app.task_execution import execute_isolated, STOP_GRACE_SECONDS, KILL_WAIT_SECONDS
from app.catalog import catalog
from app.config import plan

WORKER_ENGINE = os.getenv("WORKER_ENGINE")

def worker_url(engine):
    return "http://scanner-mcp-" + engine.replace("_", "-") + ":8000"

app = FastAPI(title="Agent Scanner · MCP")
lock = threading.Lock()
active = set()
semaphore = threading.BoundedSemaphore(2)
logger = logging.getLogger(__name__)


def safe_error(exc, config=None):
    text = str(exc)
    if config:
        target = config.get("target", {})
        for secret in list(target.get("headers", {}).values()) + [target.get("git_access_token")]:
            if secret:
                text = text.replace(secret, "[REDACTED]")
    for key in ("SNYK_TOKEN",):
        if os.getenv(key):
            text = text.replace(os.environ[key], "[REDACTED]")
    text = re.sub(r"(?i)(Bearer\s+)\S+", r"\1[REDACTED]", text)
    return text[:1600]


def now():
    return datetime.now(timezone.utc).isoformat()


def terminal_status(summary):
    if not summary["completed"]:
        return "failed"
    if summary["failed"] or summary["pending"]:
        return "partially_failed"
    return "success"


def aggregate_results(runs, total, started):
    """Checkpoint finished engines without implying complete coverage."""
    summary = dict(total=total,
                   completed=sum(r["status"] == "success" for r in runs),
                   failed=sum(r["status"] == "failed" for r in runs),
                   pending=total - len(runs))
    if total == 1 and runs:
        return {**runs[0], "summary": summary}
    return dict(
        engine="mcp-suite", engine_name="Набор MCP-проверок", engine_version="1.0",
        status="running" if summary["pending"] else terminal_status(summary),
        duration_sec=round(time.monotonic() - started, 2), summary=summary,
        findings=[f for r in runs for f in r.get("findings", [])], runs=runs,
        coverage="Покрытие определяется только успешно завершёнными движками. Ошибки движков не являются результатом проверки безопасности.",
    )


def execute_engine(task, config):
    """Worker calls are never retried; control-api retries cannot rerun tools."""
    started = time.monotonic()
    engine = next(e for e in catalog() if e["id"] == task["engine"])
    try:
        with httpx.Client(timeout=task.get("timeout_seconds", 300) + STOP_GRACE_SECONDS + KILL_WAIT_SECONDS + 20) as client:
            response = client.post(worker_url(task["engine"]) + "/execute", json=task)
            if response.is_error:
                try:
                    detail = response.json().get("detail")
                except (ValueError, AttributeError):
                    detail = None
                raise RuntimeError(detail or f"Контейнер сканера вернул HTTP {response.status_code}")
            outcome = response.json()
        if not isinstance(outcome, dict) or not isinstance(outcome.get("findings"), list):
            raise ValueError("Некорректный отчёт движка: ожидается объект с массивом findings")
        outcome.update(status="success", error=None)
    except Exception as exc:
        outcome = dict(status="failed", error=safe_error(exc, config), findings=[],
                       coverage="Движок не завершил анализ. Покрытие не подтверждено.")
    outcome.update(engine=task["engine"], engine_name=engine["name"],
                   engine_version=engine["version"], mode=task["mode"],
                   duration_sec=round(time.monotonic() - started, 2))
    return outcome


def run(scan_id):
    started = time.monotonic()
    latest_result = None
    try:
        job = control.get_scan(scan_id)
        if job["type"] != "mcp":
            raise ValueError("MCP-сервис принимает только MCP-сканы")
        c = json.loads(job["config"])
        tasks = plan(c)
        if not tasks:
            raise ValueError("Нет совместимых сканеров")
        control.patch_scan(scan_id, {"phase": "Инициализация"})
        control.post_log(scan_id, f"MCP-источник: {c.get('target', {}).get('kind', c.get('mode'))}. Проверок: {len(tasks)}", phase="Инициализация")
        control.patch_scan(scan_id, {"phase": "Проверка MCP"})
        runs = []
        initial_result = aggregate_results(runs, len(tasks), started)
        latest_result = initial_result
        control.patch_scan(scan_id, {"results": json.dumps(initial_result, ensure_ascii=False)})
        for task in tasks:
            control.post_log(scan_id, f"Выполняется {task['engine']}", phase="Проверка MCP")
            outcome = execute_engine(task, c)
            runs.append(outcome)
            result = aggregate_results(runs, len(tasks), started)
            # Retain the newest outcome even if its checkpoint cannot be sent.
            # The failure handler must not overwrite it with the previous one.
            latest_result = result
            # Commit each outcome before moving on; a later failure/restart
            # must not erase already collected reports.
            control.patch_scan(scan_id, {"results": json.dumps(result, ensure_ascii=False)})
            if outcome["status"] == "failed":
                control.post_log(scan_id, f"Ошибка {task['engine']}: {outcome['error']}", phase="Проверка MCP", level="error")
            else:
                control.post_log(scan_id, f"Завершён {task['engine']}. Находок: {len(outcome['findings'])}", phase="Проверка MCP", level="success")
        control.patch_scan(scan_id, {"phase": "Сохранение результатов"})
        summary = result["summary"]
        control.post_log(scan_id, f"Обработка завершена. Движков успешно: {summary['completed']}; с ошибкой: {summary['failed']}. Находок: {len(result['findings'])}", phase="Завершено", level="error" if summary["failed"] else "success")
        control.patch_scan(scan_id, {"status": terminal_status(summary), "phase": "Завершено", "error": None, "finished_at": now(), "results": json.dumps(result, ensure_ascii=False)})
    except Exception as exc:
        message = safe_error(exc, locals().get("c"))
        control.post_log(scan_id, message, phase="Ошибка", level="error")
        payload = {"status": "failed", "phase": "Ошибка", "error": message, "finished_at": now()}
        if latest_result:
            # An infrastructure failure still means incomplete processing,
            # even if every engine managed to produce a report beforehand.
            payload["status"] = "partially_failed" if latest_result["summary"]["completed"] else "failed"
            payload["results"] = json.dumps({**latest_result, "status": payload["status"]}, ensure_ascii=False)
        try:
            control.patch_scan(scan_id, payload)
        except Exception as persist_exc:
            # The API may still be offline after all retries. Do not disguise
            # this as a saved terminal state, or let error handling fail silently.
            logger.critical("MCP scan %s: terminal state NOT persisted (%s); "
                            "latest engine summary: %s", scan_id,
                            type(persist_exc).__name__,
                            latest_result.get("summary") if latest_result else None)
    finally:
        with lock:
            active.discard(scan_id)
        semaphore.release()


@app.on_event("startup")
def interrupted():
    if WORKER_ENGINE:
        return
    for job in control.list_scans(status="running", scan_type="mcp"):
        control.post_log(job["id"], "MCP-скан прерван перезапуском сервиса", phase="Ошибка", level="error")
        payload = {"status": "failed", "phase": "Ошибка", "error": "MCP-сервис перезапущен", "finished_at": now()}
        try:
            result = json.loads(job.get("results") or "null")
            if isinstance(result, dict) and isinstance(result.get("summary"), dict):
                payload["status"] = "partially_failed" if result["summary"].get("completed", 0) else "failed"
                payload["results"] = json.dumps({**result, "status": payload["status"]}, ensure_ascii=False)
        except (ValueError, TypeError):
            pass  # Preserve even an old/unrecognized report, without claiming success.
        control.patch_scan(job["id"], payload)


@app.get("/health")
def health():
    return {"status": "ok", "engine": WORKER_ENGINE or "coordinator"}


@app.get("/engines")
async def engines():
    if WORKER_ENGINE:
        return [e for e in catalog() if e["id"] == WORKER_ENGINE]
    values = catalog()

    async def probe(client, engine):
        try:
            # control-api allows 2 seconds for the entire schema request.
            # Probe concurrently, with a wall-clock bound per worker (not
            # just separate HTTP connect/read timeouts).
            response = await asyncio.wait_for(
                client.get(worker_url(engine["id"]) + "/engines"), timeout=0.75,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or len(payload) != 1:
                raise ValueError("Некорректный ответ worker")
            live = payload[0]
            if not isinstance(live, dict) or live.get("id") != engine["id"] or not isinstance(live.get("available"), bool):
                raise ValueError("Некорректный ответ worker")
            reason = live.get("reason")
            if reason is not None and not isinstance(reason, str):
                raise ValueError("Некорректная причина недоступности")
            engine.update(available=live["available"], reason=None if live["available"] else (reason or "Движок недоступен"))
        except (ValueError, TypeError):
            engine.update(available=False, reason="Некорректный ответ контейнера сканера")
        except Exception:
            engine.update(available=False, reason="Контейнер сканера недоступен")

    async with httpx.AsyncClient(timeout=0.5) as client:
        await asyncio.gather(*(probe(client, engine) for engine in values))
    return values


@app.get("/schema")
async def schema():
    """Описание полей конфига для динамической формы UI. Источник цели
    (remote/repository/bundle) задаётся MCP-активом, поэтому схема содержит
    только параметры самих проверок."""
    if WORKER_ENGINE:
        raise HTTPException(status_code=404)
    live_engines = await engines()
    return {
        "type": "mcp",
        "fields": [
            {
                "name": "scanner_ids",
                "label": "Движки проверок",
                "type": "enum_multi",
                "required": False,
                "default": [],
                "options": [
                    {
                        "value": engine["id"],
                        "label": engine["name"],
                        "available": engine["available"],
                        "reason": engine["reason"],
                        "cloud": engine["cloud"],
                        "modes": engine["modes"],
                        "description": engine["description"],
                    }
                    for engine in live_engines
                ],
                "help": "Пусто — локальный набор по типу цели (без Snyk).",
            },
            {
                "name": "timeout_seconds",
                "label": "Таймаут движка, сек",
                "type": "integer",
                "required": False,
                "default": 30,
                "help": "Максимум на один движок (1–300).",
            },
            {
                "name": "probes",
                "label": "Пробные вызовы",
                "type": "json",
                "required": False,
                "default": [],
                "help": "JSON-массив вызовов для динамического тестирования: {tool, arguments, contains, forbidden, expect_error}. Пусто — только инициализация и каталог.",
            },
            {
                "name": "allow_tool_calls",
                "label": "Разрешить вызовы инструментов",
                "type": "boolean",
                "required": False,
                "default": False,
                "help": "Подтверждение запуска на своём тестовом сервере; с непустыми probes обязателен.",
            },
            {
                "name": "allow_cloud",
                "label": "Передавать каталог в облако (Snyk)",
                "type": "boolean",
                "required": False,
                "default": False,
                "help": "Требуется для движка Snyk; нужен SNYK_TOKEN.",
            },
        ],
    }


@app.post("/execute")
def execute_task(task: dict):
    if not WORKER_ENGINE or task.get("engine") != WORKER_ENGINE:
        raise HTTPException(status_code=422, detail="Задача не соответствует движку контейнера")
    validate_flat(json.dumps(task))
    if not semaphore.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Контейнер занят")
    try:
        with tempfile.TemporaryDirectory(prefix="mcp-worker-") as tmp:
            return execute_isolated(task, Path(tmp))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=safe_error(exc, {"target": task})) from exc
    finally:
        semaphore.release()


@app.post("/run/{scan_id}")
def start(scan_id: int):
    if WORKER_ENGINE:
        raise HTTPException(status_code=404)
    with lock:
        if scan_id in active:
            return {"status": "already_running", "scan_id": scan_id}
        if not semaphore.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="Одновременно выполняются два MCP-скана")
        active.add(scan_id)
    threading.Thread(target=run, args=(scan_id,), daemon=True).start()
    return {"status": "started", "scan_id": scan_id}
