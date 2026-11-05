import asyncio

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import runner
from app.bridge import completion_response

app = FastAPI(title="agent-scanner scanner-garak")

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


@app.post("/run/{scan_id}")
async def run_scan(scan_id: int):
    """Запускает скан в фоновом потоке и сразу отвечает -- прогресс UI
    читает через control-api /scans/{id}/logs."""
    if runner.is_running(scan_id):
        return {"status": "already_running", "scan_id": scan_id}
    asyncio.create_task(asyncio.to_thread(runner.run_scan, scan_id))
    return {"status": "started", "scan_id": scan_id}


@app.post("/v1/chat/completions")
async def chat_completions(body: dict):
    """Bridge: OpenAI-совместимый эндпоинт для CLI garak, запросы уходят
    тестируемому агенту (см. app/bridge.py)."""
    try:
        content = runner.bridge.chat(body.get("messages") or [])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc))
    return completion_response("agent-bridge", content)
