from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    agent_configs,
    assets,
    events,
    injection,
    library,
    llm_models,
    mcp_artifacts,
    mcp_assets,
    reports,
    scans,
    scanners,
    skill_assets,
)
from app.db import init_db
from app.seed import seed_demo_data

app = FastAPI(title="agent-scanner control-api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(events.router)
app.include_router(llm_models.router)
app.include_router(agent_configs.router)
app.include_router(assets.router)
app.include_router(mcp_artifacts.router)
app.include_router(mcp_assets.router)
app.include_router(skill_assets.router)
app.include_router(scanners.router)
app.include_router(reports.router)
app.include_router(scans.router)
app.include_router(injection.router)
app.include_router(library.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    seed_demo_data()


@app.get("/health")
def health():
    return {"status": "ok"}
