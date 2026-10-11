import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import runner

app = FastAPI(title="agent-scanner scanner-sysleak")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _on_startup() -> None:
    await asyncio.to_thread(runner.fail_interrupted_scans)


@app.get("/health")
def health():
    return {"status": "ok"}


def _max_trials_default() -> int:
    import os

    return int(os.environ.get("SYSLEAK_MAX_TRIALS", "60"))


@app.get("/schema")
def schema():
    """Описание полей конфига для динамической формы UI. Список payload'ов --
    атакующие промпты из payloads.yaml, ровно те имена, что фильтрует runner."""
    from app.payloads import load_payloads

    return {
        "type": "system_prompt_leak",
        "fields": [
            {
                "name": "payloads",
                "label": "Атакующие промпты",
                "type": "enum_multi",
                "required": False,
                "default": [],
                "options": [{"value": payload["name"], "label": payload["name"]} for payload in load_payloads()],
                "help": "Пусто — используются все промпты.",
            },
            {
                "name": "repeats",
                "label": "Повторов на payload",
                "type": "integer",
                "required": False,
                "default": 1,
            },
            {
                "name": "max_trials",
                "label": "Максимум прогонов",
                "type": "integer",
                "required": False,
                "default": _max_trials_default(),
                "help": "Верхняя граница числа прогонов на скан.",
            },
        ],
    }


@app.post("/run/{scan_id}")
async def run_scan(scan_id: int):
    """Запускает скан в фоновом потоке и сразу отвечает -- прогресс UI
    читает через control-api /scans/{id}/logs."""
    if runner.is_running(scan_id):
        return {"status": "already_running", "scan_id": scan_id}
    asyncio.create_task(asyncio.to_thread(runner.run_scan, scan_id))
    return {"status": "started", "scan_id": scan_id}
