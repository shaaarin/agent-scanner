from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import LLMModel
from app.schemas import LLMModelCreate, LLMModelRead, LLMModelUpdate

router = APIRouter(prefix="/llm-models", tags=["llm-models"])


def _mask(api_key: str) -> str:
    if len(api_key) <= 4:
        return "*" * len(api_key)
    return f"{api_key[:2]}{'*' * (len(api_key) - 4)}{api_key[-2:]}"


@router.post("", response_model=LLMModel)
def create_llm_model(payload: LLMModelCreate, session: Session = Depends(get_session)):
    existing = session.exec(select(LLMModel).where(LLMModel.name == payload.name)).first()
    if existing:
        raise HTTPException(status_code=409, detail="llm model name already exists")
    llm_model = LLMModel(**payload.model_dump())
    session.add(llm_model)
    session.commit()
    session.refresh(llm_model)
    return llm_model


@router.get("", response_model=list[LLMModelRead])
def list_llm_models(session: Session = Depends(get_session)):
    llm_models = session.exec(select(LLMModel)).all()
    return [
        LLMModelRead(
            id=m.id,
            name=m.name,
            provider_type=m.provider_type,
            base_url=m.base_url,
            api_key_masked=_mask(m.api_key),
            model=m.model,
            created_at=m.created_at.isoformat(),
        )
        for m in llm_models
    ]


@router.get("/{llm_model_id}", response_model=LLMModel)
def get_llm_model(llm_model_id: int, session: Session = Depends(get_session)):
    llm_model = session.get(LLMModel, llm_model_id)
    if not llm_model:
        raise HTTPException(status_code=404, detail="llm model not found")
    return llm_model


@router.put("/{llm_model_id}", response_model=LLMModel)
def update_llm_model(llm_model_id: int, payload: LLMModelUpdate, session: Session = Depends(get_session)):
    llm_model = session.get(LLMModel, llm_model_id)
    if not llm_model:
        raise HTTPException(status_code=404, detail="llm model not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(llm_model, key, value)
    session.add(llm_model)
    session.commit()
    session.refresh(llm_model)
    return llm_model


@router.delete("/{llm_model_id}", status_code=204)
def delete_llm_model(llm_model_id: int, session: Session = Depends(get_session)):
    llm_model = session.get(LLMModel, llm_model_id)
    if not llm_model:
        raise HTTPException(status_code=404, detail="llm model not found")
    session.delete(llm_model)
    session.commit()
