import json
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlmodel import Session, delete, select

from app.db import engine, get_session
from app.models import (
    AgentConfig,
    AgentSource,
    AssetKind,
    InjectionTrial,
    MCPArtifact,
    McpAsset,
    Scan,
    ScanLog,
    ScanLogLevel,
    ScanStatus,
    ScanType,
    TrafficEvent,
)
from app.schemas import MCPScanConfig, ScanCreate, ScanLogCreate, ScanUpdate
from app.mcp_config import upgrade_flat
from app.scanner_registry import find

router = APIRouter(prefix="/scans", tags=["scans"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _log(session: Session, scan_id: int, message: str, *, level: ScanLogLevel = ScanLogLevel.INFO, phase: Optional[str] = None) -> None:
    session.add(ScanLog(scan_id=scan_id, level=level, phase=phase, message=message))


def _compose_mcp_config(asset_target: dict, scanner_params: dict) -> str:
    """Собирает Scan.config для MCP-скана: цель -- из актива, параметры
    проверок -- из запроса (scanner_ids, timeout_seconds, probes, ...).
    Неизвестные ключи отсеивает схема MCPScanConfig, так что контракт
    scanner-mcp не меняется, а конфиг нормализуется заранее."""
    try:
        config = MCPScanConfig.model_validate(upgrade_flat({"target": asset_target, **scanner_params}))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc
    return json.dumps(config.model_dump(mode="json"), ensure_ascii=False)


@router.get("")
def list_scans(
    agent_config_id: Optional[int] = Query(None),
    asset_kind: Optional[AssetKind] = Query(None),
    asset_id: Optional[int] = Query(None),
    scan_type: Optional[ScanType] = Query(None),
    status: Optional[ScanStatus] = Query(None),
) -> list[Scan]:
    """List all scans with optional filters."""
    with Session(engine) as session:
        statement = select(Scan)
        if agent_config_id is not None:
            statement = statement.where(Scan.agent_config_id == agent_config_id)
        if asset_kind is not None:
            statement = statement.where(Scan.asset_kind == asset_kind)
        if asset_id is not None:
            statement = statement.where(Scan.asset_id == asset_id)
        if scan_type is not None:
            statement = statement.where(Scan.type == scan_type)
        if status is not None:
            statement = statement.where(Scan.status == status)
        statement = statement.order_by(Scan.created_at.desc())
        return session.exec(statement).all()


@router.get("")
def list_scans(
    agent_config_id: Optional[int] = Query(None),
    scan_type: Optional[ScanType] = Query(None),
    status: Optional[ScanStatus] = Query(None),
) -> list[Scan]:
    """List all scans with optional filters."""
    with Session(engine) as session:
        statement = select(Scan)
        if agent_config_id is not None:
            statement = statement.where(Scan.agent_config_id == agent_config_id)
        if scan_type is not None:
            statement = statement.where(Scan.type == scan_type)
        if status is not None:
            statement = statement.where(Scan.status == status)
        statement = statement.order_by(Scan.created_at.desc())
        return session.exec(statement).all()


@router.get("/active")
def get_active_scan(session_id: str = Query(...)) -> Optional[dict]:
    """Get active scan for a session (for proxy to know which scan to log events for)."""
    with Session(engine) as session:
        statement = (
            select(Scan)
            .where(Scan.session_id == session_id)
            .where(Scan.status == ScanStatus.RUNNING)
            .order_by(Scan.started_at.desc())
            .limit(1)
        )
        scan = session.exec(statement).first()
        if not scan:
            return None
        return {
            "scan_id": scan.id,
            "name": scan.name,
            "type": scan.type,
            "agent_config_id": scan.agent_config_id,
            "status": scan.status,
            "config": scan.config,
        }


@router.get("/{scan_id}/agent-config")
def get_scan_agent_config(scan_id: int) -> dict:
    """Get agent config for a scan (for DeepTeam to know which agent it's testing)."""
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")

        if scan.agent_config_id is None:
            raise HTTPException(status_code=404, detail="У этого MCP-скана нет конфигурации агента")
        agent_config = session.get(AgentConfig, scan.agent_config_id)
        if not agent_config:
            raise HTTPException(status_code=404, detail="Agent config not found")

        return {
            "id": agent_config.id,
            "name": agent_config.name,
            "source": agent_config.source,
            "git_repo_url": agent_config.git_repo_url,
            "git_ref": agent_config.git_ref,
            "dockerfile_path": agent_config.dockerfile_path,
            "api_port": agent_config.api_port,
            "remote_base_url": agent_config.remote_base_url,
            "remote_headers": agent_config.remote_headers or {},
            "interaction_mode": agent_config.interaction_mode,
            "api_config": agent_config.api_config,
            "langgraph_config": agent_config.langgraph_config,
            "env_vars": {k: v for k, v in agent_config.env_vars.items() if k.startswith("OPENAI_") or k.startswith("ANTHROPIC_")},
        }


@router.post("")
def create_scan(payload: ScanCreate) -> Scan:
    """Создать скан внутри актива (раздел «Активы»). Применимость сканера к
    виду актива и валидность конфига определяются реестром сканеров."""
    registration = find(payload.type)
    if registration is None:
        raise HTTPException(status_code=400, detail=f"Для типа сканирования {payload.type} сканер пока не подключён")
    if payload.asset_kind not in registration.asset_kinds:
        raise HTTPException(
            status_code=422,
            detail=f"Сканер «{registration.name}» не работает с активами типа «{payload.asset_kind.value}»",
        )

    with Session(engine) as session:
        asset_model = {
            AssetKind.AGENT: AgentConfig,
            AssetKind.MCP: McpAsset,
            AssetKind.SKILL: None,  # сущность есть, но сканеров для skills пока нет
        }[payload.asset_kind]
        asset = session.get(asset_model, payload.asset_id) if asset_model else None
        if asset is None:
            raise HTTPException(status_code=422, detail=f"Актив («{payload.asset_kind}», id={payload.asset_id}) не найден")

        # Remote-агент не собирается платформой и его трафик к LLM не проходит
        # через наш прокси: анализ кода без репозитория, а инъекциям некуда
        # подкладываться. Осмысленно только атака по его HTTP API
        # (динамическое тестирование и PyRIT).
        _remote_interactive = (ScanType.DEEP_TEAM, ScanType.PYRIT_SCAN)
        if (
            payload.asset_kind == AssetKind.AGENT
            and getattr(asset, "source", None) == AgentSource.REMOTE
            and payload.type not in _remote_interactive
        ):
            raise HTTPException(
                status_code=422,
                detail="Для удалённого агента доступны только динамическое тестирование и PyRIT: "
                "анализу кода нужен репозиторий, а инъекциям — трафик агента через прокси платформы",
            )

        config_json = "{}"
        if payload.asset_kind == AssetKind.MCP:
            config_json = _compose_mcp_config(asset.config, payload.config)
        elif payload.asset_kind == AssetKind.AGENT:
            # Параметры сканера из динамической формы (поля его /schema).
            config_json = json.dumps(payload.config or {}, ensure_ascii=False)

        scan = Scan(
            name=payload.name.strip(),
            type=payload.type,
            asset_kind=payload.asset_kind,
            asset_id=payload.asset_id,
            # Сканеры и launcher читают только agent_config_id.
            agent_config_id=payload.asset_id if payload.asset_kind == AssetKind.AGENT else None,
            status=ScanStatus.PENDING,
            session_id=payload.session_id,
            config=config_json,
        )
        if config_json != "{}" and registration.validate_config is not None:
            registration.validate_config(config_json)
        session.add(scan)
        session.commit()
        session.refresh(scan)
        return scan


@router.get("/{scan_id}")
def get_scan(scan_id: int) -> Scan:
    """Get a scan by ID."""
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        return scan


@router.patch("/{scan_id}")
def update_scan(scan_id: int, payload: ScanUpdate) -> Scan:
    """Update scan status/progress/launch metadata (used by scanner/launcher)."""
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(scan, key, value)
        session.add(scan)
        session.commit()
        session.refresh(scan)
        return scan


@router.delete("/{scan_id}")
def delete_scan(scan_id: int) -> dict:
    """Delete a scan and its progress log."""
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        session.exec(delete(ScanLog).where(ScanLog.scan_id == scan_id))
        session.exec(delete(InjectionTrial).where(InjectionTrial.scan_id == scan_id))
        # Перехваченный трафик скана тоже удаляем: иначе осиротевшие события с
        # переиспользованными scan_id/trial_id «подмешиваются» к новому
        # скану (особенно критично для косвенных инъекций, где трафик
        # группируется по trial_id).
        session.exec(delete(TrafficEvent).where(TrafficEvent.scan_id == scan_id))
        session.delete(scan)
        session.commit()
        return {"message": "Scan deleted"}


@router.post("/{scan_id}/start")
def start_scan(scan_id: int) -> Scan:
    """Mark a scan RUNNING and hand it off to the scanner service for its type
    (see scanner_registry). The scanner works in the background; the logs it
    writes are what the scan detail page polls."""
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        if scan.status != ScanStatus.PENDING:
            raise HTTPException(status_code=400, detail="Scan can only be started from PENDING status")
        registration = find(scan.type)
        if registration is None:
            raise HTTPException(status_code=400, detail=f"Для типа сканирования {scan.type.value} сканер пока не подключён")
        if registration.validate_config is not None:
            registration.validate_config(scan.config)

        # Fresh progress log for this run.
        session.exec(delete(ScanLog).where(ScanLog.scan_id == scan_id))
        scan.status = ScanStatus.RUNNING
        scan.phase = "Запуск"
        scan.error = None
        scan.results = None
        scan.started_at = utcnow()
        scan.finished_at = None
        _log(session, scan_id, "Сканирование поставлено в очередь", phase="Запуск")
        session.add(scan)
        session.commit()
        session.refresh(scan)

    try:
        with httpx.Client(timeout=15.0) as client:
            client.post(f"{registration.url}/run/{scan_id}").raise_for_status()
    except httpx.HTTPError as exc:
        with Session(engine) as session:
            scan = session.get(Scan, scan_id)
            scan.status = ScanStatus.FAILED
            scan.phase = "Ошибка"
            scan.error = f"{registration.service} недоступен: {exc}"
            scan.finished_at = utcnow()
            _log(session, scan_id, f"Не удалось запустить {registration.service}: {exc}", level=ScanLogLevel.ERROR, phase="Ошибка")
            session.add(scan)
            session.commit()
            session.refresh(scan)
        return scan

    return scan


@router.get("/{scan_id}/logs")
def list_scan_logs(
    scan_id: int,
    after_id: int = Query(default=0),
    limit: int = Query(default=500, le=2000),
    session: Session = Depends(get_session),
) -> list[ScanLog]:
    """Incremental progress log: pass the last `id` you've seen as `after_id`."""
    statement = (
        select(ScanLog)
        .where(ScanLog.scan_id == scan_id)
        .where(ScanLog.id > after_id)
        .order_by(ScanLog.id)
        .limit(limit)
    )
    return session.exec(statement).all()


@router.post("/{scan_id}/logs")
def create_scan_log(
    scan_id: int,
    payload: ScanLogCreate,
    session: Session = Depends(get_session),
) -> ScanLog:
    """Append one progress line (called by the scanner)."""
    scan = session.get(Scan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    log = ScanLog(scan_id=scan_id, **payload.model_dump())
    session.add(log)
    session.commit()
    session.refresh(log)
    return log


@router.post("/{scan_id}/complete")
def complete_scan(scan_id: int, results: str) -> Scan:
    """Mark a scan as completed with results."""
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        if scan.status != ScanStatus.RUNNING:
            raise HTTPException(status_code=400, detail="Scan can only be completed from RUNNING status")

        scan.status = ScanStatus.COMPLETED
        scan.phase = "Завершено"
        scan.results = results
        scan.finished_at = utcnow()
        session.add(scan)
        session.commit()
        session.refresh(scan)
        return scan


@router.post("/{scan_id}/fail")
def fail_scan(scan_id: int, error: str) -> Scan:
    """Mark a scan as failed."""
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")

        scan.status = ScanStatus.FAILED
        scan.phase = "Ошибка"
        scan.error = error
        scan.results = json.dumps({"error": error})
        scan.finished_at = utcnow()
        session.add(scan)
        session.commit()
        session.refresh(scan)
        return scan
