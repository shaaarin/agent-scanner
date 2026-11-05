"""Клонирование репозитория агента для локального semgrep-анализа.

Проще, чем в scanner-promptfoo: semgrep сканирует рабочее дерево целиком,
поэтому служебные коммиты base/compare не нужны -- достаточно shallow-clone
ветки и её коммита для метаданных скана.

`git_ref` -- ветка/тег либо полный SHA коммита: SHA нельзя склоонировать
через `clone --branch`, он забирается shallow-fetch'ем (нужна поддержка на
сервере); если сервер отказывает, резерв -- полный clone и checkout,
работающий всегда.

Адрес с токеном никогда не пишется в журнал скана (см. `scrub`) и
восстанавливается в .git/config до исходного -- как в scanner-promptfoo.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

from app.git_auth import authenticated_git_url

CLONE_TIMEOUT_SECONDS = 180
GIT_TIMEOUT_SECONDS = 60

COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


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
    """Клонирует ветку/тег или полный SHA коммита и возвращает коммит."""
    git_ref = git_ref.strip()
    clone_url = authenticated_git_url(git_repo_url, access_token)
    if COMMIT_SHA_RE.fullmatch(git_ref):
        commit = _clone_commit(git_repo_url, clone_url, git_ref, dest)
    else:
        commit = _clone_branch(git_repo_url, clone_url, git_ref, dest)
    if clone_url != git_repo_url:
        # git сохраняет адрес клона с токеном в .git/config и в reflog;
        # рабочее дерево читает semgrep, и лучше, чтобы токена там не было.
        _git(["remote", "set-url", "origin", git_repo_url], dest)
        shutil.rmtree(dest / ".git" / "logs", ignore_errors=True)
    return commit


def _clone_branch(git_repo_url: str, clone_url: str, git_ref: str, dest: Path) -> str:
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
    return _git(["rev-parse", "HEAD"], dest)


def _clone_commit(git_repo_url: str, clone_url: str, sha: str, dest: Path) -> str:
    """Один коммит по SHA: shallow fetch (нужна поддержка uploadpack на
    сервере), при отказе -- полный clone и checkout, работающий всегда."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        for args in (
            ["init", "--quiet", str(dest)],
            ["-C", str(dest), "remote", "add", "origin", clone_url],
            ["-C", str(dest), "fetch", "--quiet", "--depth", "1", "origin", sha],
            ["-C", str(dest), "checkout", "--quiet", "--detach", "FETCH_HEAD"],
        ):
            result = subprocess.run(
                ["git", *args], capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS, env=env
            )
            if result.returncode != 0:
                break
        else:
            return _git(["rev-parse", "HEAD"], dest)
    except subprocess.TimeoutExpired as exc:
        raise RepoError(f"получение коммита не уложилось в {GIT_TIMEOUT_SECONDS} с") from exc
    shutil.rmtree(dest, ignore_errors=True)
    try:
        result = subprocess.run(
            ["git", "clone", "--quiet", clone_url, str(dest)],
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT_SECONDS,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise RepoError(f"клонирование не уложилось в {CLONE_TIMEOUT_SECONDS} с") from exc
    if result.returncode != 0:
        stderr = scrub(result.stderr, clone_url, git_repo_url)
        raise RepoError(f"не удалось клонировать {git_repo_url} (коммит {sha[:12]}): {stderr[:500]}")
    _git(["checkout", "--quiet", "--detach", sha], dest)
    return _git(["rev-parse", "HEAD"], dest)
