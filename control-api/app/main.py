from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import agent_configs, campaigns, events, fuzz_runs, llm_models, templates, tree_runs
from app.db import init_db
from app.seed import seed_demo_data

app = FastAPI(title="agent-scanner control-api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(templates.router)
app.include_router(campaigns.router)
app.include_router(events.router)
app.include_router(llm_models.router)
app.include_router(agent_configs.router)
app.include_router(fuzz_runs.router)
app.include_router(tree_runs.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    seed_demo_data()


@app.get("/health")
def health():
    return {"status": "ok"}
