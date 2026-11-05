"""Переменные окружения модуля аутентификации (без pydantic-settings, как и
весь остальной сервис -- сырой os.environ).

`AUTH_ENABLED` выключается, если не задан SESSION_SECRET_KEY: платформа
работает как раньше -- все эндпоинты открыты. Это режим локальной разработки;
на стенде ключ задаётся в .env."""
import os
import secrets

# Ключ подписи сессионной cookie (HttpOnly). Пустой -> случайный на старте И
# auth считается выключенным: без стабильного ключа входить нельзя (сессии
# не пережили бы рестарт, а в multi-worker uvicorn -- друг друга).
SESSION_SECRET_KEY = os.environ.get("SESSION_SECRET_KEY", "").strip()

# Системный администратор создаётся при старте, если его ещё нет: видит и
# делает всё во всех организациях, управляет пользователями и приглашениями.
ADMIN_LOGIN = os.environ.get("ADMIN_LOGIN", "").strip().lower()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()

# Явные origin'ы для CORS (cookie требует allow_credentials=True, а он не
# совместим с allow_origins=["*"]).
CORS_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.environ.get(
        "CORS_ORIGINS", "http://localhost:4173,http://localhost:5173"
    ).split(",")
    if origin.strip()
]

# Секрет машинного контура: сервисы (сканеры, launcher, mitm-прокси) шлют его
# в заголовке X-Internal-Token и получают полный доступ к API без сессии.
INTERNAL_API_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "").strip()

AUTH_ENABLED = bool(SESSION_SECRET_KEY)

# Срок жизни сессионной cookie.
SESSION_MAX_AGE = 14 * 24 * 3600

# Если ключ сессии не задан, при старте генерируем случайный только чтобы
# SessionMiddleware принял конфигурацию (вход при этом всё равно выключен).
SESSION_SECRET_FALLBACK = secrets.token_urlsafe(48)
