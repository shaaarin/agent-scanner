import asyncio
import os
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import runner

app = FastAPI(title="agent-scanner scanner-skills")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def fail_interrupted_scans() -> None:
    url = os.getenv("RABBITMQ_URL")
    if not url:
        await asyncio.to_thread(runner.fail_interrupted_scans)
        return
    from app.consumer import consume
    app.state.consumer_stop = threading.Event()
    for _ in range(runner.MAX_CONCURRENT):
        threading.Thread(target=consume, args=(url, app.state.consumer_stop), daemon=True).start()


@app.on_event("shutdown")
def stop_consumers() -> None:
    if stop := getattr(app.state, "consumer_stop", None):
        stop.set()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/schema")
def schema():
    """Описание полей конфига для динамической формы UI. Поле LLM-модели
    появится вместе с этапом LLM (D-37)."""
    return {
        "type": runner.SCAN_TYPE,
        "fields": [
            {
                "name": "engines",
                "label": "Движки анализа",
                "type": "enum_multi",
                "required": False,
                "default": runner.DEFAULT_ENGINES,
                "options": [
                    {"value": value, "label": engine["label"], "description": engine["description"]}
                    for value, engine in runner.ENGINES.items()
                ],
                "help": "Пусто -- оба движка. Проверка frontmatter SKILL.md и свои YARA-правила платформы выполняются всегда; "
                "итоговый вердикт считает платформа, вердикты движков -- справочно.",
            },
        ],
    }


@app.post("/run/{scan_id}")
def run_scan(scan_id: int):
    """Тот же контракт, что у остальных сканеров: запуск в фоне и мгновенный
    ответ; прогресс UI читает из control-api (/scans/{id}/logs)."""
    if not runner.start_in_background(scan_id):
        return {"status": "already_running", "scan_id": scan_id}
    return {"status": "started", "scan_id": scan_id}
