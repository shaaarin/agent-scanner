from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.auth.deps import accessible_org_ids, ensure_org_access, get_caller, require_machine, Caller
from app.db import get_session
from app.models import LLMModel, OrgRole
from app.schemas import LLMModelCreate, LLMModelRead, LLMModelUpdate

router = APIRouter(prefix="/llm-models", tags=["llm-models"])


def _mask(api_key: str) -> str:
    if len(api_key) <= 4:
        return "*" * len(api_key)
    return f"{api_key[:2]}{'*' * (len(api_key) - 4)}{api_key[-2:]}"


def _read(llm_model: LLMModel) -> LLMModelRead:
    return LLMModelRead(
        id=llm_model.id,
        organization_id=llm_model.organization_id,
        name=llm_model.name,
        provider_type=llm_model.provider_type,
        base_url=llm_model.base_url,
        api_key_masked=_mask(llm_model.api_key),
        model=llm_model.model,
        created_at=llm_model.created_at.isoformat(),
    )


@router.post("", response_model=LLMModelRead)
def create_llm_model(
    payload: LLMModelCreate,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
):
    # Ключи провайдеров хранятся в открытом виде -- принятый техдолг MVP,
    # но создавать их может только редактор организации.
    ensure_org_access(caller, session, payload.organization_id, min_role=OrgRole.EDITOR)
    existing = session.exec(select(LLMModel).where(LLMModel.name == payload.name)).first()
    if existing:
        raise HTTPException(status_code=409, detail="llm model name already exists")
    llm_model = LLMModel(**payload.model_dump())
    session.add(llm_model)
    session.commit()
    session.refresh(llm_model)
    return _read(llm_model)


@router.get("", response_model=list[LLMModelRead])
def list_llm_models(
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
):
    query = select(LLMModel).order_by(LLMModel.name)
    org_ids = accessible_org_ids(session, caller)
    if org_ids is not None:
        query = query.where(LLMModel.organization_id.in_(org_ids))
    return [_read(m) for m in session.exec(query).all()]


@router.get("/{llm_model_id}", response_model=LLMModel, dependencies=[Depends(require_machine)])
def get_llm_model(llm_model_id: int, session: Session = Depends(get_session)):
    """Сырая модель с api_key -- только для сервисов платформы (сканерам);
    браузер работает со списком с маскированным ключом."""
    llm_model = session.get(LLMModel, llm_model_id)
    if not llm_model:
        raise HTTPException(status_code=404, detail="llm model not found")
    return llm_model


@router.put("/{llm_model_id}", response_model=LLMModelRead)
def update_llm_model(
    llm_model_id: int,
    payload: LLMModelUpdate,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
):
    llm_model = session.get(LLMModel, llm_model_id)
    if not llm_model:
        raise HTTPException(status_code=404, detail="llm model not found")
    ensure_org_access(caller, session, llm_model.organization_id, min_role=OrgRole.EDITOR)
    updates = payload.model_dump(exclude_unset=True)
    # Пустой api_key -- "не менять" (та же семантика, что и в UI).
    if "api_key" in updates and not updates["api_key"]:
        del updates["api_key"]
    for key, value in updates.items():
        setattr(llm_model, key, value)
    session.add(llm_model)
    session.commit()
    session.refresh(llm_model)
    return _read(llm_model)


@router.delete("/{llm_model_id}", status_code=204)
def delete_llm_model(
    llm_model_id: int,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
):
    llm_model = session.get(LLMModel, llm_model_id)
    if not llm_model:
        raise HTTPException(status_code=404, detail="llm model not found")
    ensure_org_access(caller, session, llm_model.organization_id, min_role=OrgRole.ADMIN)
    session.delete(llm_model)
    session.commit()
