from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.db import get_session
from app.models import Campaign, ConversationNode, InjectionProbe, TreeRun
from app.schemas import ConversationNodeCreate, InjectionProbeCreate, TreeRunCreate, TreeRunUpdate

router = APIRouter(prefix="/tree-runs", tags=["tree-runs"])


@router.post("", response_model=TreeRun)
def create_tree_run(payload: TreeRunCreate, session: Session = Depends(get_session)):
    base_campaign = session.get(Campaign, payload.base_campaign_id)
    if not base_campaign:
        raise HTTPException(status_code=404, detail="base_campaign not found")
    tree_run = TreeRun(**payload.model_dump())
    session.add(tree_run)
    session.commit()
    session.refresh(tree_run)
    return tree_run


@router.get("", response_model=list[TreeRun])
def list_tree_runs(base_campaign_id: Optional[int] = None, session: Session = Depends(get_session)):
    query = select(TreeRun)
    if base_campaign_id is not None:
        query = query.where(TreeRun.base_campaign_id == base_campaign_id)
    return session.exec(query).all()


@router.get("/{tree_run_id}", response_model=TreeRun)
def get_tree_run(tree_run_id: int, session: Session = Depends(get_session)):
    tree_run = session.get(TreeRun, tree_run_id)
    if not tree_run:
        raise HTTPException(status_code=404, detail="tree run not found")
    return tree_run


@router.patch("/{tree_run_id}", response_model=TreeRun)
def update_tree_run(tree_run_id: int, payload: TreeRunUpdate, session: Session = Depends(get_session)):
    tree_run = session.get(TreeRun, tree_run_id)
    if not tree_run:
        raise HTTPException(status_code=404, detail="tree run not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(tree_run, key, value)
    tree_run.updated_at = datetime.now(timezone.utc)
    session.add(tree_run)
    session.commit()
    session.refresh(tree_run)
    return tree_run


@router.post("/{tree_run_id}/nodes", response_model=ConversationNode)
def create_node(tree_run_id: int, payload: ConversationNodeCreate, session: Session = Depends(get_session)):
    tree_run = session.get(TreeRun, tree_run_id)
    if not tree_run:
        raise HTTPException(status_code=404, detail="tree run not found")
    node = ConversationNode(tree_run_id=tree_run_id, **payload.model_dump())
    session.add(node)
    session.commit()
    session.refresh(node)
    return node


@router.get("/{tree_run_id}/nodes", response_model=list[ConversationNode])
def list_nodes(tree_run_id: int, session: Session = Depends(get_session)):
    query = (
        select(ConversationNode)
        .where(ConversationNode.tree_run_id == tree_run_id)
        .order_by(ConversationNode.turn_index.asc())
    )
    return session.exec(query).all()


@router.post("/{tree_run_id}/probes", response_model=InjectionProbe)
def create_probe(tree_run_id: int, payload: InjectionProbeCreate, session: Session = Depends(get_session)):
    tree_run = session.get(TreeRun, tree_run_id)
    if not tree_run:
        raise HTTPException(status_code=404, detail="tree run not found")
    probe = InjectionProbe(tree_run_id=tree_run_id, **payload.model_dump())
    session.add(probe)
    session.commit()
    session.refresh(probe)
    return probe


@router.get("/{tree_run_id}/probes", response_model=list[InjectionProbe])
def list_probes(
    tree_run_id: int,
    checkpoint_occurrence: Optional[int] = None,
    success: Optional[bool] = None,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    session: Session = Depends(get_session),
):
    query = select(InjectionProbe).where(InjectionProbe.tree_run_id == tree_run_id)
    if checkpoint_occurrence is not None:
        query = query.where(InjectionProbe.checkpoint_occurrence == checkpoint_occurrence)
    if success is not None:
        query = query.where(InjectionProbe.success == success)
    query = query.order_by(InjectionProbe.id.asc()).offset(offset).limit(limit)
    return session.exec(query).all()
