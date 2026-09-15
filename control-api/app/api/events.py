from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.db import get_session
from app.models import EventDirection, TrafficEvent
from app.schemas import TrafficEventDetail, TrafficEventDetailResponse, TrafficEventRead

router = APIRouter(prefix="/events", tags=["events"])


@router.post("", response_model=TrafficEvent)
def create_event(payload: TrafficEvent, session: Session = Depends(get_session)):
    # raw_excerpt is stored in full, untruncated -- the events page shows the
    # exact body the agent sent/received, and the proxy is the only writer.
    event = TrafficEvent(**payload.model_dump(exclude={"id"}))
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


@router.get("", response_model=list[TrafficEventRead])
def list_events(
    session_id: Optional[str] = None,
    scan_id: Optional[int] = None,
    flow_id: Optional[str] = None,
    direction: Optional[EventDirection] = None,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    session: Session = Depends(get_session),
):
    query = select(TrafficEvent)
    if session_id:
        query = query.where(TrafficEvent.session_id == session_id)
    if scan_id is not None:
        query = query.where(TrafficEvent.scan_id == scan_id)
    if flow_id:
        query = query.where(TrafficEvent.flow_id == flow_id)
    if direction is not None:
        query = query.where(TrafficEvent.direction == direction)
    query = query.order_by(TrafficEvent.created_at.desc()).offset(offset).limit(limit)
    return session.exec(query).all()


@router.get("/{event_id}", response_model=TrafficEventDetailResponse)
def get_event(event_id: int, session: Session = Depends(get_session)):
    """One event with its full body, plus the opposite-direction event of the
    same flow (request <-> response) so the UI can show the whole exchange."""
    event = session.get(TrafficEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Событие не найдено")

    other_direction = (
        EventDirection.RESPONSE if event.direction == EventDirection.REQUEST else EventDirection.REQUEST
    )
    pair = session.exec(
        select(TrafficEvent)
        .where(TrafficEvent.flow_id == event.flow_id)
        .where(TrafficEvent.direction == other_direction)
        .order_by(TrafficEvent.created_at)
        .limit(1)
    ).first()

    return TrafficEventDetailResponse(
        event=TrafficEventDetail.model_validate(event),
        pair=TrafficEventDetail.model_validate(pair) if pair else None,
    )
