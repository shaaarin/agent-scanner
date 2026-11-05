import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api import (
    agent_configs,
    assets,
    auth,
    events,
    injection,
    library,
    llm_models,
    mcp_artifacts,
    mcp_assets,
    orgs,
    repo,
    reports,
    scans,
    scanners,
    skill_assets,
)
from app.auth import config as auth_config
from app.auth.bootstrap import ensure_admin_user
from app.db import init_db
from app.seed import seed_demo_data

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="agent-scanner control-api")

# Сессия входа: подписанная HttpOnly cookie (SameSite=Lax -- куки уходят и в
# fetch с credentials: "include", и в переходы по <a href> на выгрузки).
# Пустой SESSION_SECRET_KEY = auth выключен: подставляем случайный ключ только
# чтобы middleware принял конфигурацию, вход при этом закрыт (см. config.py).
app.add_middleware(
    SessionMiddleware,
    secret_key=auth_config.SESSION_SECRET_KEY or auth_config.SESSION_SECRET_FALLBACK,
    same_site="lax",
    https_only=False,
    max_age=auth_config.SESSION_MAX_AGE,
)

# CORS добавляется после SessionMiddleware, т.е. снаружи: preflight-запросы
# обрабатываются без обращения к сессии. Cookie требует явных origin'ов.
app.add_middleware(
    CORSMiddleware,
    allow_origins=auth_config.CORS_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(orgs.router)
app.include_router(orgs.invites_router)
app.include_router(repo.router)
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
    if not auth_config.AUTH_ENABLED:
        logger.warning(
            "SESSION_SECRET_KEY не задан: авторизация выключена, все эндпоинты "
            "открыты -- режим локальной разработки"
        )
    elif not auth_config.INTERNAL_API_TOKEN:
        logger.warning(
            "INTERNAL_API_TOKEN пуст: машинный контур (сканеры, launcher, mitm-прокси) "
            "не сможет обращаться к control-api, пока секрет не задан у всех сервисов"
        )
    init_db()
    seed_demo_data()
    ensure_admin_user()


@app.get("/health")
def health():
    return {"status": "ok"}
