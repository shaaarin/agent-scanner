import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import runner

app = FastAPI(title="agent-scanner scanner-semgrep")

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


_SEVERITY_OPTIONS = [
    {"value": "low", "label": "Низкая"},
    {"value": "medium", "label": "Средняя"},
    {"value": "high", "label": "Высокая"},
]


@app.get("/schema")
def schema():
    """Описание полей конфига для динамической формы UI."""
    return {
        "type": runner.SCAN_TYPE,
        "fields": [
            {
                "name": "min_severity",
                "label": "Минимальная критичность",
                "type": "enum",
                "required": False,
                "default": runner.DEFAULT_MIN_SEVERITY,
                "options": _SEVERITY_OPTIONS,
                "help": "Находки ниже выбранного уровня в результаты не попадают.",
            },
            {
                "name": "rule_sets",
                "label": "Дополнительные наборы правил Semgrep",
                "type": "enum_multi",
                "required": False,
                "default": [],
                "options": [
                    {"value": value, "label": preset["label"], "description": preset["description"]}
                    for value, preset in runner.RULE_SETS.items()
                ],
                "help": "Базовый AI-набор платформы выполняется всегда; официальные наборы скачиваются из Semgrep Registry при скане.",
            },
            {
                "name": "custom_rules",
                "label": "Пользовательские правила Semgrep",
                "type": "text",
                "required": False,
                "help": 'Дополнительные правила в YAML (объект с полем "rules"), выполняются вместе с базовым набором.',
            },
        ],
    }


@app.post("/run/{scan_id}")
async def run_scan(scan_id: int):
    """Тот же контракт, что у остальных сканеров: запуск в фоне и мгновенный
    ответ; прогресс UI читает из control-api (/scans/{id}/logs)."""
    if runner.is_running(scan_id):
        return {"status": "already_running", "scan_id": scan_id}
    asyncio.create_task(asyncio.to_thread(runner.run_scan, scan_id))
    return {"status": "started", "scan_id": scan_id}
