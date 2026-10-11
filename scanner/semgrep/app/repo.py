"""Клонирование репозитория агента для локального semgrep-анализа.

Проще, чем в scanner-promptfoo: semgrep сканирует рабочее дерево целиком,
поэтому служебные коммиты base/compare не нужны -- достаточно shallow-clone
ветки и её коммита для метаданных скана.

Адрес с токеном никогда не пишется в журнал скана (см. `scrub`) и
восстанавливается в .git/config до исходного -- как в scanner-promptfoo.
"""
import os
import shutil
import subprocess
from pathlib import Path

from app.git_auth import authenticated_git_url

CLONE_TIMEOUT_SECONDS = 180
GIT_TIMEOUT_SECONDS = 60


class RepoError(RuntimeError):
    pass


def scrub(text: str, clone_url: str, git_repo_url: str) -> str:
    """Убирает адрес с токеном из вывода git."""
    return text.replace(clone_url, git_repo_url) if clone_url != git_repo_url else text


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RepoError(f"git {args[0]} завершился с ошибкой: {result.stderr.strip()[:500]}")
    return result.stdout.strip()


def clone(git_repo_url: str, git_ref: str, access_token: str | None, dest: Path) -> str:
    """Клонирует ветку и возвращает её коммит."""
    clone_url = authenticated_git_url(git_repo_url, access_token)
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", git_ref, clone_url, str(dest)],
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT_SECONDS,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired as exc:
        raise RepoError(f"клонирование не уложилось в {CLONE_TIMEOUT_SECONDS} с") from exc
    if result.returncode != 0:
        lines = [line for line in result.stderr.splitlines() if line.strip() and not line.startswith("Cloning into")]
        stderr = scrub("\n".join(lines), clone_url, git_repo_url)
        raise RepoError(f"не удалось клонировать {git_repo_url} (ветка {git_ref}): {stderr[:500]}")
    if clone_url != git_repo_url:
        # git сохраняет адрес клона с токеном в .git/config и в reflog;
        # рабочее дерево читает semgrep, и лучше, чтобы токена там не было.
        _git(["remote", "set-url", "origin", git_repo_url], dest)
        shutil.rmtree(dest / ".git" / "logs", ignore_errors=True)
    return _git(["rev-parse", "HEAD"], dest)
