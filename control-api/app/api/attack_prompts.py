from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import AttackPrompt
from app.schemas import AttackPromptCreate, AttackPromptUpdate

router = APIRouter(prefix="/attack-prompts", tags=["attack-prompts"])


@router.post("", response_model=AttackPrompt)
def create_attack_prompt(payload: AttackPromptCreate, session: Session = Depends(get_session)):
    existing = session.exec(select(AttackPrompt).where(AttackPrompt.name == payload.name)).first()
    if existing:
        raise HTTPException(status_code=409, detail="attack prompt name already exists")
    attack_prompt = AttackPrompt(**payload.model_dump())
    session.add(attack_prompt)
    session.commit()
    session.refresh(attack_prompt)
    return attack_prompt


@router.get("", response_model=list[AttackPrompt])
def list_attack_prompts(session: Session = Depends(get_session)):
    return session.exec(select(AttackPrompt)).all()


@router.get("/{attack_prompt_id}", response_model=AttackPrompt)
def get_attack_prompt(attack_prompt_id: int, session: Session = Depends(get_session)):
    attack_prompt = session.get(AttackPrompt, attack_prompt_id)
    if not attack_prompt:
        raise HTTPException(status_code=404, detail="attack prompt not found")
    return attack_prompt


@router.put("/{attack_prompt_id}", response_model=AttackPrompt)
def update_attack_prompt(attack_prompt_id: int, payload: AttackPromptUpdate, session: Session = Depends(get_session)):
    attack_prompt = session.get(AttackPrompt, attack_prompt_id)
    if not attack_prompt:
        raise HTTPException(status_code=404, detail="attack prompt not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(attack_prompt, key, value)
    session.add(attack_prompt)
    session.commit()
    session.refresh(attack_prompt)
    return attack_prompt


@router.delete("/{attack_prompt_id}", status_code=204)
def delete_attack_prompt(attack_prompt_id: int, session: Session = Depends(get_session)):
    attack_prompt = session.get(AttackPrompt, attack_prompt_id)
    if not attack_prompt:
        raise HTTPException(status_code=404, detail="attack prompt not found")
    session.delete(attack_prompt)
    session.commit()
