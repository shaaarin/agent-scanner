"""Копия `launcher/app/git_auth.py`: встраивает токен доступа в HTTPS-адрес
git-репозитория (`https://oauth2:<token>@host/org/repo.git`), чтобы
code-scan клонировал приватные репозитории так же, как launcher.
Держите обе копии одинаковыми.

Хранение токена в открытом виде -- принятый техдолг MVP (см.
docs/architecture.md). Адрес с токеном никогда не пишется в журнал скана:
см. `repo.scrub`.
"""
from urllib.parse import quote, urlparse, urlunparse

PAT_USERNAME_PLACEHOLDER = "oauth2"


def authenticated_git_url(git_repo_url: str, access_token: str | None) -> str:
    """No-op for non-HTTP(S) URLs (e.g. ssh:// remotes) or when no token is set."""
    if not access_token:
        return git_repo_url
    parsed = urlparse(git_repo_url)
    if parsed.scheme not in ("http", "https"):
        return git_repo_url

    netloc = f"{PAT_USERNAME_PLACEHOLDER}:{quote(access_token, safe='')}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))
