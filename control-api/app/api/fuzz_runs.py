from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.db import get_session
from app.models import Campaign, FuzzAttempt, FuzzRun
from app.schemas import FuzzAttemptCreate, FuzzRunCreate, FuzzRunUpdate

router = APIRouter(prefix="/fuzz-runs", tags=["fuzz-runs"])


@router.post("", response_model=FuzzRun)
def create_fuzz_run(payload: FuzzRunCreate, session: Session = Depends(get_session)):
    if payload.injection_target != "user_message":
        raise HTTPException(
            status_code=400,
            detail="the one-shot fuzz engine only supports injection_target=user_message (direct) -- "
            "use /tree-runs for indirect (tool_result) fuzzing",
        )
    base_campaign = session.get(Campaign, payload.base_campaign_id)
    if not base_campaign:
        raise HTTPException(status_code=404, detail="base_campaign not found")
    fuzz_run = FuzzRun(**payload.model_dump())
    session.add(fuzz_run)
    session.commit()
    session.refresh(fuzz_run)
    return fuzz_run


@router.get("", response_model=list[FuzzRun])
def list_fuzz_runs(session: Session = Depends(get_session)):
    return session.exec(select(FuzzRun)).all()


@router.get("/{fuzz_run_id}", response_model=FuzzRun)
def get_fuzz_run(fuzz_run_id: int, session: Session = Depends(get_session)):
    fuzz_run = session.get(FuzzRun, fuzz_run_id)
    if not fuzz_run:
        raise HTTPException(status_code=404, detail="fuzz run not found")
    return fuzz_run


@router.patch("/{fuzz_run_id}", response_model=FuzzRun)
def update_fuzz_run(fuzz_run_id: int, payload: FuzzRunUpdate, session: Session = Depends(get_session)):
    fuzz_run = session.get(FuzzRun, fuzz_run_id)
    if not fuzz_run:
        raise HTTPException(status_code=404, detail="fuzz run not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(fuzz_run, key, value)
    fuzz_run.updated_at = datetime.now(timezone.utc)
    session.add(fuzz_run)
    session.commit()
    session.refresh(fuzz_run)
    return fuzz_run


@router.post("/{fuzz_run_id}/attempts", response_model=FuzzAttempt)
def create_attempt(fuzz_run_id: int, payload: FuzzAttemptCreate, session: Session = Depends(get_session)):
    fuzz_run = session.get(FuzzRun, fuzz_run_id)
    if not fuzz_run:
        raise HTTPException(status_code=404, detail="fuzz run not found")
    attempt = FuzzAttempt(fuzz_run_id=fuzz_run_id, **payload.model_dump())
    session.add(attempt)
    session.commit()
    session.refresh(attempt)
    return attempt


@router.get("/{fuzz_run_id}/attempts", response_model=list[FuzzAttempt])
def list_attempts(
    fuzz_run_id: int,
    success: Optional[bool] = None,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    session: Session = Depends(get_session),
):
    query = select(FuzzAttempt).where(FuzzAttempt.fuzz_run_id == fuzz_run_id)
    if success is not None:
        query = query.where(FuzzAttempt.success == success)
    query = query.order_by(FuzzAttempt.iteration.asc()).offset(offset).limit(limit)
    return session.exec(query).all()
