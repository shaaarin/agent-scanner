import asyncio
import inspect
import re

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import runner

app = FastAPI(title="agent-scanner scanner")

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


def _humanize(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)


def _class_names(*modules) -> list[str]:
    names: list[str] = []
    for module in modules:
        for name, obj in vars(module).items():
            if not name.startswith("_") and inspect.isclass(obj) and name not in names:
                names.append(name)
    return names


@app.get("/schema")
def schema():
    """Описание полей конфига для динамической формы UI. Списки
    уязвимостей/атак перечисляются из установленной библиотеки deepteam --
    ровно те имена, которые резолвит deepteam_runner (включая алиасы)."""
    from deepteam import attacks as dt_attacks, vulnerabilities as dt_vulnerabilities
    from deepteam.attacks import single_turn as dt_single_turn

    from app.deepteam_runner import VULNERABILITY_ALIASES

    vulnerability_names = _class_names(dt_vulnerabilities) + list(VULNERABILITY_ALIASES)
    attack_names = _class_names(dt_single_turn, dt_attacks)
    return {
        "type": "deep_team",
        "fields": [
            {
                "name": "eval_llm_model_id",
                "label": "Модель-судья",
                "type": "llm_model",
                "required": True,
                "help": "Модель из раздела «LLM-модели», оценивающая ответы агента (LLM-as-a-Judge).",
            },
            {
                "name": "vulnerabilities",
                "label": "Классы уязвимостей",
                "type": "enum_multi",
                "required": False,
                "default": ["BFLA", "BOLA", "RBAC"],
                "options": [{"value": name, "label": _humanize(name)} for name in vulnerability_names],
                "help": "Пусто — базовый набор BFLA, BOLA, RBAC.",
            },
            {
                "name": "attacks",
                "label": "Атаки",
                "type": "enum_multi",
                "required": False,
                "default": ["PromptInjection"],
                "options": [{"value": name, "label": _humanize(name)} for name in attack_names],
                "help": "Пусто — только PromptInjection.",
            },
            {
                "name": "attacks_per_vulnerability_type",
                "label": "Атак на класс уязвимости",
                "type": "integer",
                "required": False,
                "default": 1,
                "help": "Больше — дольше скан и полнее покрытие.",
            },
        ],
    }


@app.post("/run/{scan_id}")
async def run_scan(scan_id: int):
    """Starts one scan in a background thread and returns immediately -- the
    UI follows progress via control-api's /scans/{id}/logs."""
    if runner.is_running(scan_id):
        return {"status": "already_running", "scan_id": scan_id}
    asyncio.create_task(asyncio.to_thread(runner.run_scan, scan_id))
    return {"status": "started", "scan_id": scan_id}
