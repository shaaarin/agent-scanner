"""Организации: владельцы активов, моделей и сканов.

- любой вошедший пользователь может создать организацию и становится её
  администратором;
- участники присоединяются по **одноразовым ссылкам-приглашениям**: admin
  создаёт ссылку с ролью (`POST /orgs/{id}/invites`), передаёт её вне
  платформы, приглашённый после входа принимает (`POST
  /invites/{token}/accept`) и получает Membership. Прямое добавление по
  логину осталось в API (`POST /orgs/{id}/members`), UI им не пользуется;
- роли внутри организации: admin / editor / reader (`OrgRole`);
- системный админ (`is_superadmin`) видит все организации и может всё.
"""
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.auth.deps import Caller, ensure_org_access, get_caller, org_role
from app.auth.passwords import hash_password, password_problems
from app.db import get_session
from app.models import Invite, Membership, Organization, OrgRole, User, utcnow
from app.schemas import (
    InviteCreate,
    InviteInfo,
    InviteRead,
    MemberCreate,
    MemberRead,
    MemberUpdate,
    OrganizationCreate,
    OrganizationRead,
    OrganizationUpdate,
)

router = APIRouter(prefix="/orgs", tags=["orgs"])
# Публичные и «принимающие» эндпоинты приглашений -- без префикса /orgs.
invites_router = APIRouter(tags=["invites"])


def _get_org(org_id: int, session: Session) -> Organization:
    org = session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Организация не найдена")
    return org


def _members_count(session: Session, org_id: int) -> int:
    return len(
        session.exec(select(Membership.id).where(Membership.org_id == org_id)).all()
    )


def _org_read(session: Session, org: Organization, caller: Caller) -> OrganizationRead:
    my_role = None
    if caller.is_human and not caller.unrestricted:
        my_role = org_role(session, caller.user.id, org.id)
    elif caller.is_human and caller.user.is_superadmin:
        # Системный админ видит и свою роль, если он состоит в организации.
        my_role = org_role(session, caller.user.id, org.id)
    return OrganizationRead(
        id=org.id,
        name=org.name,
        description=org.description,
        created_at=org.created_at,
        my_role=my_role,
        members_count=_members_count(session, org.id),
    )


@router.get("", response_model=list[OrganizationRead])
def list_orgs(caller: Caller = Depends(get_caller), session: Session = Depends(get_session)):
    """Свои организации (системный админ и машинный контур -- все)."""
    query = select(Organization).order_by(Organization.name)
    if not caller.unrestricted and caller.is_human:
        query = (
            select(Organization)
            .join(Membership, Membership.org_id == Organization.id)
            .where(Membership.user_id == caller.user.id)
            .order_by(Organization.name)
        )
    orgs = session.exec(query).all()
    return [_org_read(session, org, caller) for org in orgs]


@router.post("", response_model=OrganizationRead, status_code=201)
def create_org(
    payload: OrganizationCreate,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
):
    """Создать организацию; создатель становится её администратором."""
    if not caller.is_human:
        raise HTTPException(status_code=403, detail="Организации создаёт человек, а не сервис платформы")
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Название организации не может быть пустым")
    org = Organization(name=name, description=payload.description, created_by_user_id=caller.user.id)
    session.add(org)
    session.flush()
    session.add(Membership(user_id=caller.user.id, org_id=org.id, role=OrgRole.ADMIN))
    session.commit()
    session.refresh(org)
    return _org_read(session, org, caller)


@router.get("/{org_id}", response_model=OrganizationRead)
def get_org(org_id: int, caller: Caller = Depends(get_caller), session: Session = Depends(get_session)):
    org = _get_org(org_id, session)
    ensure_org_access(caller, session, org.id)
    return _org_read(session, org, caller)


@router.patch("/{org_id}", response_model=OrganizationRead)
def update_org(
    org_id: int,
    payload: OrganizationUpdate,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
):
    """Переименовать организацию / поменять описание (admin организации)."""
    org = _get_org(org_id, session)
    ensure_org_access(caller, session, org.id, min_role=OrgRole.ADMIN)
    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates:
        updates["name"] = (updates["name"] or "").strip()
        if not updates["name"]:
            raise HTTPException(status_code=422, detail="Название организации не может быть пустым")
    for key, value in updates.items():
        setattr(org, key, value)
    session.add(org)
    session.commit()
    session.refresh(org)
    return _org_read(session, org, caller)


@router.get("/{org_id}/members", response_model=list[MemberRead])
def list_members(org_id: int, caller: Caller = Depends(get_caller), session: Session = Depends(get_session)):
    org = _get_org(org_id, session)
    ensure_org_access(caller, session, org.id)
    rows = session.exec(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.org_id == org_id)
        .order_by(User.login)
    ).all()
    return [
        MemberRead(
            user_id=user.id,
            login=user.login,
            display_name=user.display_name,
            email=user.email,
            is_superadmin=user.is_superadmin,
            role=membership.role,
            last_login_at=user.last_login_at,
        )
        for membership, user in rows
    ]


@router.post("/{org_id}/members", response_model=MemberRead, status_code=201)
def add_member(
    org_id: int,
    payload: MemberCreate,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
):
    """Пригласить участника по логину (admin организации). Пользователя можно
    создать сразу с паролем -- удобно, чтобы выдать учётку на руки."""
    org = _get_org(org_id, session)
    ensure_org_access(caller, session, org.id, min_role=OrgRole.ADMIN)
    login = payload.login.strip().lower()
    if not login:
        raise HTTPException(status_code=422, detail="Логин не может быть пустым")
    if payload.password is not None:
        problems = password_problems(payload.password)
        if problems:
            raise HTTPException(
                status_code=422,
                detail="Пароль не соответствует строгой политике. Требуется: " + ", ".join(problems),
            )
    user = session.exec(select(User).where(User.login == login)).first()
    if user is None:
        user = User(
            login=login,
            display_name=login,
            # Пароль сразу -- учётка готова к выдаче; без него -- «тихая»
            # запись, пароль задаст владелец при регистрации.
            password_hash=hash_password(payload.password) if payload.password else None,
        )
        session.add(user)
        session.flush()
    existing = session.exec(
        select(Membership)
        .where(Membership.user_id == user.id)
        .where(Membership.org_id == org.id)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Этот пользователь уже участник организации")
    membership = Membership(user_id=user.id, org_id=org.id, role=payload.role)
    session.add(membership)
    session.commit()
    session.refresh(membership)
    return MemberRead(
        user_id=user.id,
        login=user.login,
        display_name=user.display_name,
        email=user.email,
        is_superadmin=user.is_superadmin,
        role=membership.role,
        last_login_at=user.last_login_at,
    )


@router.patch("/{org_id}/members/{user_id}", response_model=MemberRead)
def update_member(
    org_id: int,
    user_id: int,
    payload: MemberUpdate,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
):
    org = _get_org(org_id, session)
    ensure_org_access(caller, session, org.id, min_role=OrgRole.ADMIN)
    membership = session.exec(
        select(Membership)
        .where(Membership.user_id == user_id)
        .where(Membership.org_id == org.id)
    ).first()
    if not membership:
        raise HTTPException(status_code=404, detail="Участник не найден")
    # Не оставляем организацию без администратора.
    admins = session.exec(
        select(Membership).where(Membership.org_id == org.id).where(Membership.role == OrgRole.ADMIN)
    ).all()
    if (
        membership.role == OrgRole.ADMIN
        and payload.role != OrgRole.ADMIN
        and len(admins) == 1
        and admins[0].user_id == user_id
    ):
        raise HTTPException(status_code=409, detail="Нельзя понизить последнего администратора организации")
    membership.role = payload.role
    session.add(membership)
    session.commit()
    user = session.get(User, user_id)
    return MemberRead(
        user_id=user.id,
        login=user.login,
        display_name=user.display_name,
        email=user.email,
        is_superadmin=user.is_superadmin,
        role=membership.role,
        last_login_at=user.last_login_at,
    )


@router.delete("/{org_id}/members/{user_id}", status_code=204)
def remove_member(
    org_id: int,
    user_id: int,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
):
    org = _get_org(org_id, session)
    ensure_org_access(caller, session, org.id, min_role=OrgRole.ADMIN)
    membership = session.exec(
        select(Membership)
        .where(Membership.user_id == user_id)
        .where(Membership.org_id == org.id)
    ).first()
    if not membership:
        raise HTTPException(status_code=404, detail="Участник не найден")
    admins = session.exec(
        select(Membership).where(Membership.org_id == org.id).where(Membership.role == OrgRole.ADMIN)
    ).all()
    if membership.role == OrgRole.ADMIN and len(admins) == 1:
        raise HTTPException(status_code=409, detail="Нельзя удалить последнего администратора организации")
    session.delete(membership)
    session.commit()


def _invite_read(invite: Invite) -> InviteRead:
    return InviteRead(
        id=invite.id,
        role=invite.role,
        token=invite.token,
        created_at=invite.created_at,
        used=invite.used_at is not None,
    )


@router.post("/{org_id}/invites", response_model=InviteRead, status_code=201)
def create_invite(
    org_id: int,
    payload: InviteCreate,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
):
    """Создать одноразовую ссылку-приглашение с ролью (admin организации)."""
    org = _get_org(org_id, session)
    ensure_org_access(caller, session, org.id, min_role=OrgRole.ADMIN)
    invite = Invite(
        org_id=org.id,
        role=payload.role,
        token=secrets.token_urlsafe(24),
        created_by_user_id=caller.user.id if caller.is_human else None,
    )
    session.add(invite)
    session.commit()
    session.refresh(invite)
    return _invite_read(invite)


@router.get("/{org_id}/invites", response_model=list[InviteRead])
def list_invites(
    org_id: int,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
):
    """Активные и использованные ссылки организации (admin)."""
    org = _get_org(org_id, session)
    ensure_org_access(caller, session, org.id, min_role=OrgRole.ADMIN)
    invites = session.exec(
        select(Invite).where(Invite.org_id == org_id).order_by(Invite.created_at.desc(), Invite.id.desc())
    ).all()
    return [_invite_read(invite) for invite in invites]


@router.delete("/{org_id}/invites/{invite_id}", status_code=204)
def revoke_invite(
    org_id: int,
    invite_id: int,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
):
    """Отозвать ссылку (admin): удаление делает токен недействительным."""
    org = _get_org(org_id, session)
    ensure_org_access(caller, session, org.id, min_role=OrgRole.ADMIN)
    invite = session.get(Invite, invite_id)
    if not invite or invite.org_id != org.id:
        raise HTTPException(status_code=404, detail="Приглашение не найдено")
    session.delete(invite)
    session.commit()


@invites_router.get("/invites/{token}", response_model=InviteInfo)
def get_invite_info(token: str, session: Session = Depends(get_session)) -> InviteInfo:
    """Куда ведёт ссылка -- для страницы приглашения. Публичный: секретом
    служит сам токен; использованная ссылка помечается valid=false."""
    invite = session.exec(select(Invite).where(Invite.token == token)).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Приглашение не найдено")
    org = session.get(Organization, invite.org_id)
    return InviteInfo(
        org_name=org.name if org else "?",
        role=invite.role,
        valid=invite.used_at is None,
    )


@invites_router.post("/invites/{token}/accept")
def accept_invite(
    token: str,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
):
    """Принять приглашение (только человек, сессия обязательна): создаёт
    Membership с ролью ссылки и помечает её использованной."""
    if not caller.is_human:
        raise HTTPException(status_code=403, detail="Приглашения принимает человек, а не сервис платформы")
    invite = session.exec(select(Invite).where(Invite.token == token)).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Приглашение не найдено")
    if invite.used_at is not None:
        raise HTTPException(status_code=409, detail="Ссылка уже использована")
    org = session.get(Organization, invite.org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Организация приглашения не найдена")
    existing = session.exec(
        select(Membership)
        .where(Membership.user_id == caller.user.id)
        .where(Membership.org_id == org.id)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Вы уже участник этой организации")

    membership = Membership(user_id=caller.user.id, org_id=org.id, role=invite.role)
    session.add(membership)
    invite.used_by_user_id = caller.user.id
    invite.used_at = utcnow()
    session.add(invite)
    session.commit()
    session.refresh(membership)
    return {"org_id": org.id, "org_name": org.name, "role": membership.role}
