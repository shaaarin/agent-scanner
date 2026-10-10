from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.db import get_session
from app.models import EventDirection, TrafficEvent
from app.schemas import TrafficEventDetail, TrafficEventDetailResponse

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


@router.get("", response_model=list[TrafficEventDetail])
def list_events(
    session_id: Optional[str] = None,
    scan_id: Optional[int] = None,
    trial_id: Optional[int] = None,
    flow_id: Optional[str] = None,
    direction: Optional[EventDirection] = None,
    include_body: bool = False,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    session: Session = Depends(get_session),
):
    # Список по умолчанию без тел (`raw_excerpt`), чтобы длинная таблица
    # событий оставалась лёгкой. `include_body=true` отдаёт тела целиком --
    # им пользуется scanner-indirect, которому нужны tool_calls и метки из
    # перехваченных запросов/ответов.
    query = select(TrafficEvent)
    if session_id:
        query = query.where(TrafficEvent.session_id == session_id)
    if scan_id is not None:
        query = query.where(TrafficEvent.scan_id == scan_id)
    if trial_id is not None:
        query = query.where(TrafficEvent.trial_id == trial_id)
    if flow_id:
        query = query.where(TrafficEvent.flow_id == flow_id)
    if direction is not None:
        query = query.where(TrafficEvent.direction == direction)
    query = query.order_by(TrafficEvent.created_at.desc()).offset(offset).limit(limit)
    rows = session.exec(query).all()
    if include_body:
        return [TrafficEventDetail.model_validate(r) for r in rows]
    # Явно гасим raw_excerpt: ответ типизирован TrafficEventDetail, но в
    # лёгком режиме тело не отдаём.
    return [TrafficEventDetail.model_validate(r).model_copy(update={"raw_excerpt": ""}) for r in rows]


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
