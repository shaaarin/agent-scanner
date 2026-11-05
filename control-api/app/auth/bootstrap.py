"""Бутстрап системного администратора из переменных окружения.

При старте: если заданы ADMIN_LOGIN/ADMIN_PASSWORD и пользователя с таким
логином нет -- создаётся is_superadmin. Если пользователь есть, пароль НЕ
перезаписывается (правка пароля -- руками в БД или через пересоздание); если
пароля у существующего admin-логина нет, он выставляется из окружения."""
import logging

from sqlmodel import Session, select

from app.auth import config as auth_config
from app.auth.passwords import hash_password
from app.db import engine
from app.models import User

logger = logging.getLogger("uvicorn.error")


def ensure_admin_user() -> None:
    if not auth_config.ADMIN_LOGIN or not auth_config.ADMIN_PASSWORD:
        return
    with Session(engine) as session:
        user = session.exec(select(User).where(User.login == auth_config.ADMIN_LOGIN)).first()
        if user is None:
            session.add(
                User(
                    login=auth_config.ADMIN_LOGIN,
                    password_hash=hash_password(auth_config.ADMIN_PASSWORD),
                    display_name=auth_config.ADMIN_LOGIN,
                    is_superadmin=True,
                )
            )
            session.commit()
            logger.info("Создан системный администратор %s", auth_config.ADMIN_LOGIN)
        elif not user.password_hash:
            # «Тихая» запись от приглашения, оказавшаяся админ-логином.
            user.password_hash = hash_password(auth_config.ADMIN_PASSWORD)
            session.add(user)
            session.commit()
            logger.info("Задан пароль из окружения для администратора %s", auth_config.ADMIN_LOGIN)
