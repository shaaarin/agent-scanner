"""Клонирование git-репозитория skill-актива (D-42). По образцу
`scanner/semgrep/app/repo.py` -- общий код между сканерами не выносится.

Отличия от semgrep: `core.symlinks=false` (симлинк становится обычным файлом с
текстом цели и не ведёт за пределы клона), без сабмодулей, только протоколы
http/https (`file://` и ssh из конфига актива не читают файлы контейнера), таймаут
-- не дольше остатка дедлайна скана. `git_ref` -- ветка/тег либо полный SHA:
SHA нельзя склоонировать через `clone --branch`, он забирается shallow-fetch'ем
(нужна поддержка на сервере), при отказе -- полный clone и checkout. После
клона `.git` удаляется: движкам нужна только рабочая копия, а в `.git` остался
бы адрес репозитория.

Адрес с токеном никогда не пишется в журнал скана (см. `scrub`).
"""
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

from app.git_auth import authenticated_git_url

CLONE_TIMEOUT_SECONDS = 180
GIT_TIMEOUT_SECONDS = 60
ALLOWED_PROTOCOLS = "http:https"

COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


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
    """Клонирует ветку/тег или полный SHA коммита, возвращает коммит и удаляет `.git`."""
    git_ref = git_ref.strip()
    clone_url = authenticated_git_url(git_repo_url, access_token)
    limit = CLONE_TIMEOUT_SECONDS if timeout is None else max(1.0, min(CLONE_TIMEOUT_SECONDS, timeout))
    if COMMIT_SHA_RE.fullmatch(git_ref):
        _clone_commit(git_repo_url, clone_url, git_ref, dest, limit)
    else:
        _clone_branch(git_repo_url, clone_url, git_ref, dest, limit)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=dest, capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS, env=_env()
    )
    if commit.returncode != 0:
        raise RepoError(f"git rev-parse завершился с ошибкой: {commit.stderr.strip()[:300]}")
    _drop_git(dest)
    return commit.stdout.strip()


def _clone_branch(git_repo_url: str, clone_url: str, git_ref: str, dest: Path, limit: float) -> None:
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


def _clone_commit(git_repo_url: str, clone_url: str, sha: str, dest: Path, limit: float) -> None:
    """Один коммит по SHA: shallow fetch (нужна поддержка uploadpack на
    сервере), при отказе -- полный clone и checkout, работающий всегда."""
    flags = ["-c", "core.symlinks=false", "-c", "core.hooksPath=/dev/null"]
    try:
        for args in (
            ["init", "--quiet", str(dest)],
            ["-C", str(dest), "remote", "add", "origin", clone_url],
            ["-C", str(dest), "fetch", "--quiet", "--depth", "1", "origin", sha],
            ["-C", str(dest), "checkout", "--quiet", "--detach", "FETCH_HEAD"],
        ):
            result = subprocess.run(
                ["git", *flags, *args], capture_output=True, text=True, timeout=limit, env=_env()
            )
            if result.returncode != 0:
                break
        else:
            return
    except subprocess.TimeoutExpired as exc:
        raise RepoError(f"клонирование не уложилось в {limit:.0f} с") from exc
    shutil.rmtree(dest, ignore_errors=True)
    result = subprocess.run(
        ["git", *flags, "clone", "--quiet", "--no-recurse-submodules", "--", clone_url, str(dest)],
        capture_output=True,
        text=True,
        timeout=limit,
        env=_env(),
    )
    if result.returncode != 0:
        lines = [line for line in result.stderr.splitlines() if line.strip() and not line.startswith("Cloning into")]
        stderr = scrub("\n".join(lines), clone_url, git_repo_url)
        raise RepoError(f"не удалось клонировать {git_repo_url} (коммит {sha[:12]}): {stderr[:500]}")
    checkout = subprocess.run(
        ["git", *flags, "-C", str(dest), "checkout", "--quiet", "--detach", sha],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
        env=_env(),
    )
    if checkout.returncode != 0:
        stderr = scrub(checkout.stderr, clone_url, git_repo_url)
        raise RepoError(f"git checkout завершился с ошибкой: {stderr.strip()[:300]}")


def _drop_git(dest: Path) -> None:
    """Удаляет `.git` после клона. На Windows git делает pack-файлы
    read-only, и rmtree с ignore_errors молча оставляет их -- снимаем
    атрибут вручную."""
    root = dest / ".git"
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_file():
            try:
                path.chmod(stat.S_IWRITE)
            except OSError:
                pass
    shutil.rmtree(root, ignore_errors=True)


def measure(root: Path) -> tuple[int, int]:
    """(число файлов, суммарный размер) рабочей копии -- для лимитов."""
    files = size = 0
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            files += 1
            size += path.stat().st_size
    return files, size
