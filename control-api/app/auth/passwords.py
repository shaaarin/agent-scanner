"""Хэширование паролей стандартным scrypt из stdlib -- без внешних зависимостей.

Формат хранения: `scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>`, соль случайная на
пароль; проверка -- постоянным сравнением. Слабые параметры намеренно не
принимаются на входе хранимой строки, чтобы подложенный хэш не ослабил
проверку."""
import base64
import hashlib
import re
import secrets

_ALGORITHM = "scrypt"
_N, _R, _P = 2**14, 8, 1

# Строгая политика пароля -- единая для регистрации и приглашений.
MIN_PASSWORD_LEN = 10


def password_problems(password: str) -> list[str]:
    """Нарушения строгой политики пароля (пустой список = пароль принят).

    Требования: минимум 10 символов, заглавная и строчная буквы (латиница или
    кириллица), цифра и спецсимвол (всё, что не буква и не цифра)."""
    problems: list[str] = []
    if len(password) < MIN_PASSWORD_LEN:
        problems.append(f"минимум {MIN_PASSWORD_LEN} символов (сейчас {len(password)})")
    if not re.search(r"[A-ZА-ЯЁ]", password):
        problems.append("заглавная буква")
    if not re.search(r"[a-zа-яё]", password):
        problems.append("строчная буква")
    if not re.search(r"[0-9]", password):
        problems.append("цифра")
    if not re.search(r"[^A-Za-zА-Яа-яЁё0-9]", password):
        problems.append("спецсимвол (например !@#$%)")
    return problems


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P)
    return "$".join(
        (
            _ALGORITHM,
            str(_N),
            str(_R),
            str(_P),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(derived).decode("ascii"),
        )
    )


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algorithm, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algorithm != _ALGORITHM:
            return False
        n, r, p = int(n), int(r), int(p)
        # Проверяем, что параметры в хэше разумные, иначе считаем хэш
        # повреждённым, а не «лёгким» (memory 32*n*r байт).
        if not (2**10 <= n <= 2**22 and 1 <= r <= 64 and 1 <= p <= 8):
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p)
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(derived, expected)
