import json
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlmodel import Session, delete, select

from app.db import engine, get_session
from app.models import AgentConfig, MCPArtifact, Scan, ScanLog, ScanLogLevel, ScanStatus, ScanType
from app.schemas import MCPBundleTarget, MCPScanConfig, ScanLogCreate, ScanUpdate

router = APIRouter(prefix="/scans", tags=["scans"])

# Каждый тип скана выполняет свой сервис-сканер с одинаковым контрактом
# (`POST /run/{scan_id}`, прогресс и результаты -- обратно в control-api).
# Тип без сканера (mcp, agent_skills) запустить нельзя.
SCANNERS: dict[ScanType, tuple[str, str]] = {
    ScanType.DEEP_TEAM: (
        "scanner-deepteam",
        os.environ.get("SCANNER_DEEPTEAM_URL", "http://scanner-deepteam:8000"),
    ),
    ScanType.CODE_SCAN: (
        "scanner-promptfoo",
        os.environ.get("SCANNER_PROMPTFOO_URL", "http://scanner-promptfoo:8000"),
    ),
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _log(session: Session, scan_id: int, message: str, *, level: ScanLogLevel = ScanLogLevel.INFO, phase: Optional[str] = None) -> None:
    session.add(ScanLog(scan_id=scan_id, level=level, phase=phase, message=message))


def _validate_scan_for_create(scan: Scan) -> Optional[MCPScanConfig]:
    """Validate the target and type-specific config before persistence."""
    if scan.type in (ScanType.DEEP_TEAM, ScanType.CODE_SCAN) and scan.agent_config_id is None:
        raise HTTPException(status_code=422, detail="Для этого типа сканирования требуется конфигурация агента")

    if scan.type != ScanType.MCP:
        return None
    if scan.agent_config_id is not None:
        raise HTTPException(status_code=422, detail="Для MCP-сканирования конфигурация агента не используется")

    try:
        raw_config = json.loads(scan.config or "{}")
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="config должен содержать JSON-объект") from exc
    if not isinstance(raw_config, dict):
        raise HTTPException(status_code=422, detail="config MCP-сканирования должен быть JSON-объектом")

    try:
        config = MCPScanConfig.model_validate(raw_config)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    # Persist normalized values so scanner-mcp receives one stable contract.
    scan.config = json.dumps(config.model_dump(mode="json"), ensure_ascii=False)
    return config


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

        agent_config = session.get(AgentConfig, scan.agent_config_id)
        if not agent_config:
            raise HTTPException(status_code=404, detail="Agent config not found")

        return {
            "id": agent_config.id,
            "name": agent_config.name,
            "git_repo_url": agent_config.git_repo_url,
            "git_ref": agent_config.git_ref,
            "dockerfile_path": agent_config.dockerfile_path,
            "api_port": agent_config.api_port,
            "interaction_mode": agent_config.interaction_mode,
            "api_config": agent_config.api_config,
            "langgraph_config": agent_config.langgraph_config,
            "env_vars": {k: v for k, v in agent_config.env_vars.items() if k.startswith("OPENAI_") or k.startswith("ANTHROPIC_")},
        }


@router.post("")
def create_scan(scan: Scan) -> Scan:
    """Create a new scan."""
    mcp_config = _validate_scan_for_create(scan)
    with Session(engine) as session:
        if mcp_config and isinstance(mcp_config.target, MCPBundleTarget):
            if not session.get(MCPArtifact, mcp_config.target.artifact_id):
                raise HTTPException(status_code=422, detail="Указанный MCPB-артефакт не найден")
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
        session.delete(scan)
        session.commit()
        return {"message": "Scan deleted"}


@router.post("/{scan_id}/start")
def start_scan(scan_id: int) -> Scan:
    """Mark a scan RUNNING and hand it off to the scanner service for its type
    (see SCANNERS). The scanner works in the background; the logs it writes
    are what the scan detail page polls."""
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        if scan.status != ScanStatus.PENDING:
            raise HTTPException(status_code=400, detail="Scan can only be started from PENDING status")
        if scan.type not in SCANNERS:
            raise HTTPException(status_code=400, detail=f"Для типа сканирования {scan.type.value} сканер пока не подключён")
        scanner_name, scanner_url = SCANNERS[scan.type]

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
            client.post(f"{scanner_url}/run/{scan_id}").raise_for_status()
    except httpx.HTTPError as exc:
        with Session(engine) as session:
            scan = session.get(Scan, scan_id)
            scan.status = ScanStatus.FAILED
            scan.phase = "Ошибка"
            scan.error = f"{scanner_name} недоступен: {exc}"
            scan.finished_at = utcnow()
            _log(session, scan_id, f"Не удалось запустить {scanner_name}: {exc}", level=ScanLogLevel.ERROR, phase="Ошибка")
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
