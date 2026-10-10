"""Эндпоинты косвенных инъекций.

Два потребителя:

- **scanner-indirect** создаёт прогоны (`POST /scans/{id}/trials`), по одному
  переводит в `running`, отправляет агенту задачу и пишет вердикт
  (`PATCH /trials/{id}`);
- **proxy** на каждом `chat/completions` спрашивает `GET /scans/{id}/injection/active`
  и, если есть активный прогон с инъекцией, дописывает payload в результат
  нужного инструмента. Директива отдаётся без кэша: иначе она «протекла» бы
  в следующий прогон.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.db import get_session
from app.models import InjectionTrial, InjectionTrialStatus, Scan
from app.schemas import InjectionTrialCreate, InjectionTrialUpdate

router = APIRouter(tags=["injection"])


@router.get("/scans/{scan_id}/injection/active")
def get_active_injection(scan_id: int, session: Session = Depends(get_session)) -> Optional[dict]:
    """Директива для прокси: что подложить в текущем прогоне. `null` -- в
    скане нет активного прогона (прокси тогда ничего не меняет)."""
    trial = session.exec(
        select(InjectionTrial)
        .where(InjectionTrial.scan_id == scan_id)
        .where(InjectionTrial.status == InjectionTrialStatus.RUNNING)
        .order_by(InjectionTrial.id.desc())
        .limit(1)
    ).first()
    if not trial:
        return None
    point = trial.injection_point
    # Базовый прогон (indirect) активен, чтобы прокси пометил трафик trial_id,
    # но инъекцию не несёт. Для system_prompt инъекция -- это метка canary в
    # системном сообщении; для tool_result -- payload в результате инструмента.
    if trial.baseline:
        inject = False
    elif point == "system_prompt":
        inject = bool(trial.canary)
    else:
        inject = bool(trial.target_tool and trial.payload_text)
    return {
        "trial_id": trial.id,
        "inject": inject,
        "injection_point": point,
        "target_tool": trial.target_tool,
        "occurrence": trial.occurrence,
        "mode": trial.mode,
        "payload_text": trial.payload_text if (inject and point == "tool_result") else None,
        "canary": trial.canary if (inject and point == "system_prompt") else None,
    }


@router.post("/scans/{scan_id}/trials", response_model=InjectionTrial)
def create_trial(scan_id: int, payload: InjectionTrialCreate, session: Session = Depends(get_session)) -> InjectionTrial:
    if not session.get(Scan, scan_id):
        raise HTTPException(status_code=404, detail="Scan not found")
    trial = InjectionTrial(scan_id=scan_id, **payload.model_dump())
    session.add(trial)
    session.commit()
    session.refresh(trial)
    return trial


@router.get("/scans/{scan_id}/trials", response_model=list[InjectionTrial])
def list_trials(
    scan_id: int,
    status: Optional[InjectionTrialStatus] = Query(None),
    session: Session = Depends(get_session),
) -> list[InjectionTrial]:
    statement = select(InjectionTrial).where(InjectionTrial.scan_id == scan_id)
    if status is not None:
        statement = statement.where(InjectionTrial.status == status)
    statement = statement.order_by(InjectionTrial.id)
    return session.exec(statement).all()


@router.patch("/trials/{trial_id}", response_model=InjectionTrial)
def update_trial(trial_id: int, payload: InjectionTrialUpdate, session: Session = Depends(get_session)) -> InjectionTrial:
    trial = session.get(InjectionTrial, trial_id)
    if not trial:
        raise HTTPException(status_code=404, detail="Trial not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(trial, key, value)
    session.add(trial)
    session.commit()
    session.refresh(trial)
    return trial
