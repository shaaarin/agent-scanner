"""Вход по логину и паролю и данные текущего пользователя.

- `POST /auth/login {login, password}` -- проверка пароля, сессионная cookie;
- `POST /auth/register {login, password, display_name?}` -- открытая
  регистрация: новый пользователь или «тихая» запись, созданная приглашением
  в организацию (тогда пароль прикрепляется к ней); сессия ставится сразу;
- `POST /auth/logout` -- очистка сессии;
- `GET /auth/me` -- пользователь и его организации (или `auth_enabled: false`
  в режиме без auth, когда SESSION_SECRET_KEY не задан).

Системный администратор (`is_superadmin`) создаётся при старте из
`ADMIN_LOGIN`/`ADMIN_PASSWORD` -- см. app/auth/bootstrap.py.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.auth import config as auth_config
from app.auth.deps import user_from_session
from app.auth.passwords import hash_password, password_problems, verify_password
from app.db import get_session
from app.models import Membership, Organization, User, utcnow

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    login: str = Field(min_length=1)
    password: str = Field(min_length=1)


class RegisterRequest(BaseModel):
    login: str = Field(min_length=1)
    password: str = Field(min_length=1)
    display_name: Optional[str] = None
    email: Optional[str] = None


def _normalize_login(raw: str) -> str:
    login = raw.strip().lower()
    if not login:
        raise HTTPException(status_code=422, detail="Логин не может быть пустым")
    return login


def _check_password_strength(password: str) -> None:
    problems = password_problems(password)
    if problems:
        raise HTTPException(
            status_code=422,
            detail="Пароль не соответствует строгой политике. Требуется: " + ", ".join(problems),
        )


def _authenticate(session: Session, login: str, password: str) -> Optional[User]:
    user = session.exec(select(User).where(User.login == login)).first()
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


def _start_session(request: Request, user: User, session: Session) -> None:
    user.last_login_at = utcnow()
    session.add(user)
    session.commit()
    request.session["user_id"] = user.id


@router.post("/login")
def login(payload: LoginRequest, request: Request, session: Session = Depends(get_session)):
    if not auth_config.AUTH_ENABLED:
        raise HTTPException(status_code=404, detail="Авторизация не настроена (SESSION_SECRET_KEY не задан)")
    login_normalized = _normalize_login(payload.login)
    user = _authenticate(session, login_normalized, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    _start_session(request, user, session)
    return {"ok": True, "user_id": user.id}


@router.post("/register", status_code=201)
def register(payload: RegisterRequest, request: Request, session: Session = Depends(get_session)):
    """Открытая регистрация. Если логин совпал с «тихой» записью от
    приглашения (без пароля) -- запись активируется; занятый логин с паролем
    -- 409."""
    if not auth_config.AUTH_ENABLED:
        raise HTTPException(status_code=404, detail="Авторизация не настроена (SESSION_SECRET_KEY не задан)")
    login_normalized = _normalize_login(payload.login)
    _check_password_strength(payload.password)
    user = session.exec(select(User).where(User.login == login_normalized)).first()
    if user is None:
        user = User(
            login=login_normalized,
            password_hash=hash_password(payload.password),
            display_name=(payload.display_name or "").strip() or login_normalized,
            email=(payload.email or "").strip() or None,
        )
    elif not user.password_hash:
        # Приглашённый, зарегистрировавшийся со своим логином.
        user.password_hash = hash_password(payload.password)
        if (payload.display_name or "").strip():
            user.display_name = payload.display_name.strip()
        if (payload.email or "").strip():
            user.email = payload.email.strip()
    else:
        raise HTTPException(status_code=409, detail="Этот логин уже занят")
    _start_session(request, user, session)
    return {"ok": True, "user_id": user.id}


@router.post("/logout", status_code=204)
def logout(request: Request):
    request.session.clear()


@router.get("/me")
def me(request: Request, session: Session = Depends(get_session)):
    """Текущий пользователь и его организации. `auth_enabled: false` -- режим
    разработки без входа: интерфейс работает без логина."""
    if not auth_config.AUTH_ENABLED:
        return {"auth_enabled": False, "user": None, "memberships": []}
    user = user_from_session(request, session)
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется вход")
    rows = session.exec(
        select(Membership, Organization)
        .join(Organization, Organization.id == Membership.org_id)
        .where(Membership.user_id == user.id)
        .order_by(Organization.name)
    ).all()
    return {
        "auth_enabled": True,
        "user": {
            "id": user.id,
            "login": user.login,
            "display_name": user.display_name,
            "email": user.email,
            "is_superadmin": user.is_superadmin,
        },
        "memberships": [
            {"org_id": membership.org_id, "org_name": org.name, "role": membership.role}
            for membership, org in rows
        ],
    }
