from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.db import get_session
from app.models import TrafficEvent

router = APIRouter(prefix="/events", tags=["events"])

MAX_RAW_EXCERPT_BYTES = 4096


@router.post("", response_model=TrafficEvent)
def create_event(payload: TrafficEvent, session: Session = Depends(get_session)):
    event = TrafficEvent(**payload.model_dump(exclude={"id"}))
    if len(event.raw_excerpt) > MAX_RAW_EXCERPT_BYTES:
        event.raw_excerpt = event.raw_excerpt[:MAX_RAW_EXCERPT_BYTES]
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


@router.get("", response_model=list[TrafficEvent])
def list_events(
    session_id: Optional[str] = None,
    campaign_id: Optional[int] = None,
    injected: Optional[bool] = None,
    success_detected: Optional[bool] = None,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    session: Session = Depends(get_session),
):
    query = select(TrafficEvent)
    if session_id:
        query = query.where(TrafficEvent.session_id == session_id)
    if campaign_id is not None:
        query = query.where(TrafficEvent.campaign_id == campaign_id)
    if injected is not None:
        query = query.where(TrafficEvent.injected == injected)
    if success_detected is not None:
        query = query.where(TrafficEvent.success_detected == success_detected)
    query = query.order_by(TrafficEvent.created_at.desc()).offset(offset).limit(limit)
    return session.exec(query).all()
