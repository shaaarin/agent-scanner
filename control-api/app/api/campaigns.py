from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session, select

from app.db import get_session
from app.models import Campaign, CampaignStatus, InjectionTemplate
from app.schemas import ActiveCampaignResponse, CampaignCreate, CampaignUpdate

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def _deactivate_other_campaigns(session: Session, session_id: str, except_id: Optional[int] = None) -> None:
    others = session.exec(
        select(Campaign).where(
            Campaign.session_id == session_id,
            Campaign.status == CampaignStatus.ACTIVE,
        )
    ).all()
    for other in others:
        if other.id == except_id:
            continue
        other.status = CampaignStatus.PAUSED
        other.updated_at = datetime.now(timezone.utc)
        session.add(other)


@router.post("", response_model=Campaign)
def create_campaign(payload: CampaignCreate, session: Session = Depends(get_session)):
    template = session.get(InjectionTemplate, payload.template_id)
    if not template:
        raise HTTPException(status_code=404, detail="template not found")
    campaign = Campaign(**payload.model_dump())
    if campaign.status == CampaignStatus.ACTIVE:
        _deactivate_other_campaigns(session, campaign.session_id)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return campaign


@router.get("", response_model=list[Campaign])
def list_campaigns(
    session_id: Optional[str] = None,
    status: Optional[CampaignStatus] = None,
    session: Session = Depends(get_session),
):
    query = select(Campaign)
    if session_id:
        query = query.where(Campaign.session_id == session_id)
    if status:
        query = query.where(Campaign.status == status)
    return session.exec(query).all()


@router.get("/active", response_model=Optional[ActiveCampaignResponse])
def get_active_campaign(session_id: str, response: Response, session: Session = Depends(get_session)):
    campaign = session.exec(
        select(Campaign).where(
            Campaign.session_id == session_id,
            Campaign.status == CampaignStatus.ACTIVE,
        )
    ).first()
    if not campaign:
        response.status_code = 204
        return None
    template = session.get(InjectionTemplate, campaign.template_id)
    if not template:
        response.status_code = 204
        return None

    return ActiveCampaignResponse(
        campaign_id=campaign.id,
        session_id=campaign.session_id,
        status=campaign.status,
        injection_rate=campaign.injection_rate,
        inject_at_occurrence=campaign.inject_at_occurrence,
        template_id=template.id,
        template=template,
    )


@router.get("/{campaign_id}", response_model=Campaign)
def get_campaign(campaign_id: int, session: Session = Depends(get_session)):
    campaign = session.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="campaign not found")
    return campaign


@router.patch("/{campaign_id}", response_model=Campaign)
def update_campaign(campaign_id: int, payload: CampaignUpdate, session: Session = Depends(get_session)):
    campaign = session.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="campaign not found")
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(campaign, key, value)
    campaign.updated_at = datetime.now(timezone.utc)
    if updates.get("status") == CampaignStatus.ACTIVE:
        _deactivate_other_campaigns(session, campaign.session_id, except_id=campaign.id)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return campaign


@router.delete("/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: int, session: Session = Depends(get_session)):
    campaign = session.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="campaign not found")
    session.delete(campaign)
    session.commit()
