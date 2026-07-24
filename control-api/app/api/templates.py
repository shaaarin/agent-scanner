from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import InjectionTemplate
from app.schemas import InjectionTemplateCreate, InjectionTemplateUpdate

router = APIRouter(prefix="/templates", tags=["templates"])


@router.post("", response_model=InjectionTemplate)
def create_template(payload: InjectionTemplateCreate, session: Session = Depends(get_session)):
    existing = session.exec(select(InjectionTemplate).where(InjectionTemplate.name == payload.name)).first()
    if existing:
        raise HTTPException(status_code=409, detail="template name already exists")
    template = InjectionTemplate(**payload.model_dump())
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


@router.get("", response_model=list[InjectionTemplate])
def list_templates(session: Session = Depends(get_session)):
    return session.exec(select(InjectionTemplate)).all()


@router.get("/{template_id}", response_model=InjectionTemplate)
def get_template(template_id: int, session: Session = Depends(get_session)):
    template = session.get(InjectionTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="template not found")
    return template


@router.put("/{template_id}", response_model=InjectionTemplate)
def update_template(template_id: int, payload: InjectionTemplateUpdate, session: Session = Depends(get_session)):
    template = session.get(InjectionTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="template not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(template, key, value)
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: int, session: Session = Depends(get_session)):
    template = session.get(InjectionTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="template not found")
    session.delete(template)
    session.commit()
