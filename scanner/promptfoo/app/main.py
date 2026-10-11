import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import runner

app = FastAPI(title="agent-scanner scanner-promptfoo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def fail_interrupted_scans() -> None:
    await asyncio.to_thread(runner.fail_interrupted_scans)


@app.get("/health")
def health():
    return {"status": "ok"}


_SEVERITY_LABELS = {"critical": "Критическая", "high": "Высокая", "medium": "Средняя", "low": "Низкая"}


@app.get("/schema")
def schema():
    """Описание полей конфига для динамической формы UI."""
    from app.promptfoo import SEVERITIES

    return {
        "type": "code_scan",
        "fields": [
            {
                "name": "min_severity",
                "label": "Минимальная критичность",
                "type": "enum",
                "required": False,
                "default": "medium",
                "options": [{"value": severity, "label": _SEVERITY_LABELS.get(severity, severity)} for severity in SEVERITIES],
                "help": "Находки ниже выбранного уровня в результаты не попадают.",
            },
            {
                "name": "guidance",
                "label": "Указания для анализа",
                "type": "text",
                "required": False,
                "help": "На что анализатору обратить внимание при проверке кода.",
            },
        ],
    }


@app.post("/run/{scan_id}")
async def run_scan(scan_id: int):
    """Тот же контракт, что у scanner-deepteam: запуск в фоне и мгновенный
    ответ; прогресс UI читает из control-api (/scans/{id}/logs)."""
    if runner.is_running(scan_id):
        return {"status": "already_running", "scan_id": scan_id}
    asyncio.create_task(asyncio.to_thread(runner.run_scan, scan_id))
    return {"status": "started", "scan_id": scan_id}
