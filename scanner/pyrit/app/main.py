import asyncio
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
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).replace(" Converter", "")


@app.get("/schema")
def schema():
    """Описание полей конфига для динамической формы UI. Стратегии и
    конвертеры -- константы pyrit_runner (конвертеры -- отфильтрованный
    белый список установленных, без LLM-зависимых)."""
    from app.pyrit_runner import CONVERTER_WHITELIST, DEFAULT_OBJECTIVES, DEFAULT_STRATEGIES, STRATEGY_LABELS

    strategy_options = [
        {"value": name, "label": label} for name, label in STRATEGY_LABELS.items()
    ]
    return {
        "type": "pyrit_scan",
        "fields": [
            {
                "name": "eval_llm_model_id",
                "label": "Модель-судья",
                "type": "llm_model",
                "required": True,
                "help": "Модель из раздела «LLM-модели»: судит ответы агента и ведёт атаку в многораундовых стратегиях.",
            },
            {
                "name": "objectives",
                "label": "Цели атак",
                "type": "text_list",
                "required": False,
                "help": f"Какие вредоносные задачи пытаться выполнить через агента, по одной в строке. "
                f"Пусто — базовый набор из {len(DEFAULT_OBJECTIVES)} целей.",
            },
            {
                "name": "strategies",
                "label": "Стратегии атак",
                "type": "enum_multi",
                "required": False,
                "default": DEFAULT_STRATEGIES,
                "options": strategy_options,
                "help": "PromptSending — одиночные промпты; RedTeaming — адверсариальная модель ведёт диалог до цели; "
                "Crescendo — постепенная эскалация от невинных вопросов.",
            },
            {
                "name": "converters",
                "label": "Конвертеры промптов",
                "type": "enum_multi",
                "required": False,
                "default": [],
                "options": [{"value": name, "label": _humanize(name)} for name in CONVERTER_WHITELIST],
                "help": "Искажения цели для PromptSending (Base64, ROT13 и т.п.): каждая пара «цель × конвертер» — "
                "отдельная атака. Пусто — отправлять цель как есть.",
            },
            {
                "name": "max_turns",
                "label": "Раундов на многораундовую атаку",
                "type": "integer",
                "required": False,
                "default": 5,
                "help": "Максимум раундов диалога для RedTeaming и Crescendo. Больше — дольше скан и полнее атаки.",
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
