from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import AgentConfig, Scan
from app.schemas import AgentConfigCreate, AgentConfigUpdate

router = APIRouter(prefix="/agent-configs", tags=["agent-configs"])


@router.post("", response_model=AgentConfig)
def create_agent_config(payload: AgentConfigCreate, session: Session = Depends(get_session)):
    existing = session.exec(select(AgentConfig).where(AgentConfig.name == payload.name)).first()
    if existing:
        raise HTTPException(status_code=409, detail="agent config name already exists")
    agent_config = AgentConfig(**payload.model_dump())
    session.add(agent_config)
    session.commit()
    session.refresh(agent_config)
    return agent_config


@router.get("", response_model=list[AgentConfig])
def list_agent_configs(session: Session = Depends(get_session)):
    return session.exec(select(AgentConfig)).all()


@router.get("/{agent_config_id}", response_model=AgentConfig)
def get_agent_config(agent_config_id: int, session: Session = Depends(get_session)):
    agent_config = session.get(AgentConfig, agent_config_id)
    if not agent_config:
        raise HTTPException(status_code=404, detail="agent config not found")
    return agent_config


@router.put("/{agent_config_id}", response_model=AgentConfig)
def update_agent_config(agent_config_id: int, payload: AgentConfigUpdate, session: Session = Depends(get_session)):
    agent_config = session.get(AgentConfig, agent_config_id)
    if not agent_config:
        raise HTTPException(status_code=404, detail="agent config not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(agent_config, key, value)
    session.add(agent_config)
    session.commit()
    session.refresh(agent_config)
    return agent_config


@router.delete("/{agent_config_id}", status_code=204)
def delete_agent_config(agent_config_id: int, session: Session = Depends(get_session)):
    agent_config = session.get(AgentConfig, agent_config_id)
    if not agent_config:
        raise HTTPException(status_code=404, detail="agent config not found")
    # Понятный 409 вместо IntegrityError от внешнего ключа: без этой проверки
    # сканы агента остались бы без конфигурации и не открывались бы и не запускались.
    scans = session.exec(select(Scan).where(Scan.agent_config_id == agent_config_id)).all()
    if scans:
        raise HTTPException(
            status_code=409,
            detail=f"У агента есть сканирования ({len(scans)}): сначала удалите их на странице «Сканирования»",
        )
    session.delete(agent_config)
    session.commit()
