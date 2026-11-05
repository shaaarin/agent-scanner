"""Клонирование репозитория агента и подготовка его к promptfoo code-scans.

promptfoo сканирует только изменения между двумя коммитами (`base...compare`),
а платформе нужен аудит всего кода ветки. Поэтому в том же клоне создаются
два служебных коммита, без копирования файлов и без отдельного репозитория:

    base    -- коммит с пустым деревом и без родителей;
    compare -- коммит с деревом проверяемой ветки, родитель -- base.

Для promptfoo это изменение «добавлены все файлы ветки». Рабочее дерево
клона остаётся на проверяемом коммите, так что серверный агент promptfoo,
дочитывающий файлы через filesystem-MCP, видит тот же код.

`git_ref` -- ветка/тег либо полный SHA коммита: SHA нельзя склоонировать
через `clone --branch`, он забирается shallow-fetch'ем (нужна поддержка на
сервере); если сервер отказывает, резерв -- полный clone и checkout,
работающий всегда.
"""
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.git_auth import authenticated_git_url

CLONE_TIMEOUT_SECONDS = 180
GIT_TIMEOUT_SECONDS = 60

COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")

# Служебные коммиты создаются от имени платформы, а не автора репозитория.
_GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "agent-scanner",
    "GIT_AUTHOR_EMAIL": "agent-scanner@localhost",
    "GIT_COMMITTER_NAME": "agent-scanner",
    "GIT_COMMITTER_EMAIL": "agent-scanner@localhost",
}


class RepoError(RuntimeError):
    pass


@dataclass
class PreparedRepo:
    path: Path
    commit: str  # реальный коммит проверяемой ветки
    base: str  # служебный пустой коммит
    compare: str  # служебный коммит с деревом ветки
    files: int  # сколько файлов попадает в анализ до фильтров promptfoo


def scrub(text: str, clone_url: str, git_repo_url: str) -> str:
    """Убирает адрес с токеном из вывода git."""
    return text.replace(clone_url, git_repo_url) if clone_url != git_repo_url else text


def _git(args: list[str], cwd: Path, *, env: dict | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
        env=env,
    )
    if result.returncode != 0:
        raise RepoError(f"git {args[0]} завершился с ошибкой: {result.stderr.strip()[:500]}")
    return result.stdout.strip()


def clone(git_repo_url: str, git_ref: str, access_token: str | None, dest: Path) -> None:
    """Клонирует ветку/тег или полный SHA коммита."""
    git_ref = git_ref.strip()
    clone_url = authenticated_git_url(git_repo_url, access_token)
    if COMMIT_SHA_RE.fullmatch(git_ref):
        _clone_commit(git_repo_url, clone_url, git_ref, dest)
    else:
        _clone_branch(git_repo_url, clone_url, git_ref, dest)
    if clone_url != git_repo_url:
        # git сохраняет адрес клона с токеном в .git/config и в reflog, а
        # каталог клона целиком читает облако Promptfoo через filesystem-MCP.
        _git(["remote", "set-url", "origin", git_repo_url], dest)
        shutil.rmtree(dest / ".git" / "logs", ignore_errors=True)


def _clone_branch(git_repo_url: str, clone_url: str, git_ref: str, dest: Path) -> None:
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


def _clone_commit(git_repo_url: str, clone_url: str, sha: str, dest: Path) -> None:
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
            return
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


def prepare(path: Path) -> PreparedRepo:
    """Создаёт служебные коммиты base/compare в уже клонированном репозитории."""
    env = {**os.environ, **_GIT_IDENTITY}
    commit = _git(["rev-parse", "HEAD"], path)
    empty_tree = _empty_tree(path)
    base = _git(["commit-tree", empty_tree, "-m", "agent-scanner: пустая база"], path, env=env)
    compare = _git(
        ["commit-tree", f"{commit}^{{tree}}", "-p", base, "-m", f"agent-scanner: код {commit[:12]}"],
        path,
        env=env,
    )
    changed = _git(["diff", "--name-only", base, compare], path)
    files = len([line for line in changed.splitlines() if line.strip()])
    return PreparedRepo(path=path, commit=commit, base=base, compare=compare, files=files)


def _empty_tree(path: Path) -> str:
    result = subprocess.run(
        ["git", "mktree"],
        cwd=path,
        input="",
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RepoError(f"git mktree завершился с ошибкой: {result.stderr.strip()[:500]}")
    return result.stdout.strip()
