from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from sqlmodel import Session, select

from app.db import engine
from app.models import Scan, ScanStatus, ScanType, AgentConfig

router = APIRouter(prefix="/scans", tags=["scans"])


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
    with Session(engine) as session:
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


@router.delete("/{scan_id}")
def delete_scan(scan_id: int) -> dict:
    """Delete a scan."""
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        session.delete(scan)
        session.commit()
        return {"message": "Scan deleted"}


@router.post("/{scan_id}/start")
def start_scan(scan_id: int) -> Scan:
    """Start a scan (changes status to RUNNING)."""
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        if scan.status != ScanStatus.PENDING:
            raise HTTPException(status_code=400, detail="Scan can only be started from PENDING status")
        
        scan.status = ScanStatus.RUNNING
        scan.started_at = utcnow()
        session.commit()
        session.refresh(scan)
        return scan


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
        scan.results = results
        scan.finished_at = utcnow()
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
        scan.results = f'{{"error": "{error}"}}'
        scan.finished_at = utcnow()
        session.commit()
        session.refresh(scan)
        return scan


def utcnow():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)
