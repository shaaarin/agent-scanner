"""Клонирование git-репозитория skill-актива (D-42). По образцу
`scanner/semgrep/app/repo.py` -- общий код между сканерами не выносится.

Отличия от semgrep: `core.symlinks=false` (симлинк становится обычным файлом с
текстом цели и не ведёт за пределы клона), без сабмодулей, только протоколы
http/https (`file://` и ssh из конфига актива не читают файлы контейнера), таймаут
-- не дольше остатка дедлайна скана. После клона `.git` удаляется: движкам
нужна только рабочая копия, а в `.git` остался бы адрес репозитория.

Адрес с токеном никогда не пишется в журнал скана (см. `scrub`).
"""
import os
import shutil
import subprocess
from pathlib import Path

from app.git_auth import authenticated_git_url

CLONE_TIMEOUT_SECONDS = 180
GIT_TIMEOUT_SECONDS = 60
ALLOWED_PROTOCOLS = "http:https"


class RepoError(RuntimeError):
    pass


def scrub(text: str, clone_url: str, git_repo_url: str) -> str:
    """Убирает адрес с токеном из вывода git."""
    return text.replace(clone_url, git_repo_url) if clone_url != git_repo_url else text


def _env() -> dict[str, str]:
    return {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        # Перекрывает protocol.*.allow: file://, ssh, ext и т.п. запрещены.
        "GIT_ALLOW_PROTOCOL": ALLOWED_PROTOCOLS,
        # Глобальные и системные настройки git контейнера не влияют на клон.
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }


def clone(git_repo_url: str, git_ref: str, access_token: str | None, dest: Path, *, timeout: float | None = None) -> str:
    """Клонирует ветку/тег в `dest`, возвращает коммит и удаляет `.git`."""
    clone_url = authenticated_git_url(git_repo_url, access_token)
    limit = CLONE_TIMEOUT_SECONDS if timeout is None else max(1.0, min(CLONE_TIMEOUT_SECONDS, timeout))
    cmd = [
        "git",
        "-c", "core.symlinks=false",
        "-c", "core.hooksPath=/dev/null",
        "clone", "--quiet", "--depth", "1", "--single-branch", "--no-recurse-submodules",
        "--branch", git_ref, "--", clone_url, str(dest),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=limit, env=_env())
    except subprocess.TimeoutExpired as exc:
        raise RepoError(f"клонирование не уложилось в {limit:.0f} с") from exc
    if result.returncode != 0:
        lines = [line for line in result.stderr.splitlines() if line.strip() and not line.startswith("Cloning into")]
        stderr = scrub("\n".join(lines), clone_url, git_repo_url)
        raise RepoError(f"не удалось клонировать {git_repo_url} (ветка {git_ref}): {stderr[:500]}")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=dest, capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS, env=_env()
    )
    if commit.returncode != 0:
        raise RepoError(f"git rev-parse завершился с ошибкой: {commit.stderr.strip()[:300]}")
    shutil.rmtree(dest / ".git", ignore_errors=True)
    return commit.stdout.strip()


def measure(root: Path) -> tuple[int, int]:
    """(число файлов, суммарный размер) рабочей копии -- для лимитов."""
    files = size = 0
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            files += 1
            size += path.stat().st_size
    return files, size
