import asyncio
import json
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
from app.adapters import scan
from app.catalog import catalog
from app.config import plan

WORKER_ENGINE = os.getenv("WORKER_ENGINE")

def worker_url(engine):
    return "http://scanner-mcp-" + engine.replace("_", "-") + ":8000"

app = FastAPI(title="Agent Scanner · MCP")
lock = threading.Lock()
active = set()
semaphore = threading.BoundedSemaphore(2)


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


def run(scan_id):
    started = time.monotonic()
    try:
        job = control.get_scan(scan_id)
        if job["type"] != "mcp":
            raise ValueError("MCP-сервис принимает только MCP-сканы")
        c = json.loads(job["config"])
        tasks = plan(c)
        control.patch_scan(scan_id, {"phase": "Инициализация"})
        control.post_log(scan_id, f"MCP-источник: {c.get('target', {}).get('kind', c.get('mode'))}. Проверок: {len(tasks)}", phase="Инициализация")
        control.patch_scan(scan_id, {"phase": "Проверка MCP"})
        runs = []
        for task in tasks:
            control.post_log(scan_id, f"Выполняется {task['engine']}", phase="Проверка MCP")
            task_started = time.monotonic()
            with httpx.Client(timeout=task.get("timeout_seconds", 300) + 20) as client:
                response = client.post(worker_url(task["engine"]) + "/execute", json=task)
                if response.is_error:
                    raise RuntimeError(response.json().get("detail", "Ошибка контейнера сканера"))
                outcome = response.json()
            engine = next(e for e in catalog() if e["id"] == task["engine"])
            outcome.update(engine=task["engine"], engine_name=engine["name"], engine_version=engine["version"], mode=task["mode"], duration_sec=round(time.monotonic()-task_started, 2))
            runs.append(outcome)
        result = runs[0] if len(runs) == 1 else dict(engine="mcp-suite", engine_name="Набор MCP-проверок", engine_version="1.0", duration_sec=round(time.monotonic()-started, 2), findings=[f for r in runs for f in r.get("findings", [])], runs=runs, coverage="Каждый движок имеет отдельную область покрытия; подробности ниже.")
        control.patch_scan(scan_id, {"phase": "Сохранение результатов"})
        control.post_log(scan_id, f"Завершено. Находок: {len(result.get('findings', []))}", phase="Завершено", level="success")
        control.patch_scan(scan_id, {"status": "completed", "phase": "Завершено", "finished_at": now(), "results": json.dumps(result, ensure_ascii=False)})
    except Exception as exc:
        message = safe_error(exc, locals().get("c"))
        control.post_log(scan_id, message, phase="Ошибка", level="error")
        control.patch_scan(scan_id, {"status": "failed", "phase": "Ошибка", "error": message, "finished_at": now()})
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
        control.patch_scan(job["id"], {"status": "failed", "phase": "Ошибка", "error": "MCP-сервис перезапущен", "finished_at": now()})


@app.get("/health")
def health():
    return {"status": "ok", "engine": WORKER_ENGINE or "coordinator"}


@app.get("/engines")
def engines():
    if WORKER_ENGINE:
        return [e for e in catalog() if e["id"] == WORKER_ENGINE]
    values = catalog()
    for engine in values:
        try:
            response = httpx.get(worker_url(engine["id"]) + "/engines", timeout=2)
            response.raise_for_status()
            live = response.json()[0]
            engine.update(available=live["available"], reason=live["reason"])
        except Exception:
            engine.update(available=False, reason="Контейнер сканера недоступен")
    return values


@app.get("/schema")
def schema():
    """Описание полей конфига для динамической формы UI. Источник цели
    (remote/repository/bundle) задаётся MCP-активом, поэтому схема содержит
    только параметры самих проверок."""
    if WORKER_ENGINE:
        raise HTTPException(status_code=404)
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
                        "cloud": engine["cloud"],
                        "modes": engine["modes"],
                        "description": engine["description"],
                    }
                    for engine in catalog()
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
            return scan(task, Path(tmp))
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
