"""Зависимости FastAPI: кто вызвал эндпоинт и что ему можно.

Два вида вызовов:
- **браузер** -- HttpOnly сессионная cookie, ставится после входа по логину
  и паролю; доступ ограничен организациями пользователя и его ролью в них;
- **сервис платформы** (сканеры, launcher, mitm-прокси) -- заголовок
  `X-Internal-Token` с общим секретом; полный доступ без сессии.

Когда auth выключен (не задан SESSION_SECRET_KEY), все проверки проходят:
платформа ведёт себя как до появления авторизации.
"""
import secrets
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlmodel import Session, select

from app.auth import config as auth_config
from app.db import get_session
from app.models import Membership, OrgRole, User

# Порядок ролей: больше -- больше прав.
ROLE_LEVEL = {OrgRole.READER: 0, OrgRole.EDITOR: 1, OrgRole.ADMIN: 2}
INTERNAL_TOKEN_HEADER = "X-Internal-Token"


@dataclass
class Caller:
    """Кто вызвал эндпоинт. `user is None` + `is_machine` -- сервис платформы
    с валидным токеном (или auth выключен); иначе -- вошедший пользователь."""

    user: Optional[User]
    is_machine: bool

    @property
    def unrestricted(self) -> bool:
        """Видит и делает всё: машинный контур или системный админ."""
        return self.is_machine or bool(self.user and self.user.is_superadmin)

    @property
    def is_human(self) -> bool:
        return self.user is not None


def is_machine(request: Request) -> bool:
    """Валидный `X-Internal-Token` в запросе (сравнение постоянного времени)."""
    if not auth_config.INTERNAL_API_TOKEN:
        return False
    provided = request.headers.get(INTERNAL_TOKEN_HEADER, "")
    return secrets.compare_digest(provided, auth_config.INTERNAL_API_TOKEN)


def user_from_session(request: Request, session: Session) -> Optional[User]:
    if not auth_config.AUTH_ENABLED:
        return None
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return session.get(User, user_id)


def get_caller(
    request: Request, session: Session = Depends(get_session)
) -> Caller:
    """Основная зависимость защищённых эндпоинтов: 401, если ни сессии, ни
    машинного токена (когда auth включён)."""
    if not auth_config.AUTH_ENABLED:
        # Режим разработки: как до появления авторизации.
        return Caller(user=None, is_machine=True)
    if is_machine(request):
        return Caller(user=None, is_machine=True)
    user = user_from_session(request, session)
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется вход")
    return Caller(user=user, is_machine=False)


def require_machine(request: Request) -> None:
    """Эндпоинт только для сервисов платформы (машинный контур)."""
    if not auth_config.AUTH_ENABLED:
        return
    if not is_machine(request):
        raise HTTPException(status_code=403, detail="Доступ только для сервисов платформы")


def org_role(session: Session, user_id: int, org_id: int) -> Optional[OrgRole]:
    membership = session.exec(
        select(Membership).where(Membership.user_id == user_id).where(Membership.org_id == org_id)
    ).first()
    return membership.role if membership else None


def ensure_org_access(
    caller: Caller,
    session: Session,
    org_id: Optional[int],
    min_role: OrgRole = OrgRole.READER,
) -> None:
    """403, если у caller нет в организации роли не ниже `min_role`.
    `org_id is None` (строка без владельца) доступна только unrestricted."""
    if caller.unrestricted:
        return
    if not caller.is_human or org_id is None:
        raise HTTPException(status_code=403, detail="Нет доступа к этой организации")
    role = org_role(session, caller.user.id, org_id)
    if role is None or ROLE_LEVEL[role] < ROLE_LEVEL[min_role]:
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав: требуется роль «"
            + {OrgRole.READER: "наблюдатель", OrgRole.EDITOR: "редактор", OrgRole.ADMIN: "администратор"}[min_role]
            + "»",
        )


def accessible_org_ids(session: Session, caller: Caller) -> Optional[list[int]]:
    """Организации, чьё содержимое видно caller'у.

    None -- без ограничений (машинный контур или системный админ), иначе
    список id организаций пользователя (может быть пустым)."""
    if caller.unrestricted:
        return None
    if not caller.is_human:
        return []
    rows = session.exec(
        select(Membership.org_id).where(Membership.user_id == caller.user.id)
    ).all()
    return list(rows)
