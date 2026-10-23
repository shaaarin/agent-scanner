"""Клонирование git-актива (D-42) на настоящем git с локальным репозиторием."""
import os
import subprocess

import pytest

from app import git_auth, repo

from conftest import skill_md


def _git(cwd, *args):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
    )


@pytest.fixture
def origin(tmp_path):
    """Локальный репозиторий: скилл, симлинк наружу и сабмодуль-ссылка в .gitmodules."""
    src = tmp_path / "origin"
    (src / "skills" / "demo").mkdir(parents=True)
    (src / "skills" / "demo" / "SKILL.md").write_text(skill_md("demo"))
    os.symlink("/etc/passwd", src / "skills" / "demo" / "passwd-link")
    _git(src, "init", "-q", "-b", "main")
    _git(src, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "add", "-A")
    _git(src, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "-m", "init")
    _git(src, "tag", "v1")
    return src


@pytest.fixture
def allow_file(monkeypatch):
    monkeypatch.setattr(repo, "ALLOWED_PROTOCOLS", "file")


def test_clone_returns_commit_and_drops_git(origin, tmp_path, allow_file):
    dest = tmp_path / "clone"
    commit = repo.clone(f"file://{origin}", "main", None, dest)
    assert len(commit) == 40
    assert (dest / "skills" / "demo" / "SKILL.md").is_file()
    assert not (dest / ".git").exists()


def test_clone_by_tag(origin, tmp_path, allow_file):
    assert len(repo.clone(f"file://{origin}", "v1", None, tmp_path / "c")) == 40


def test_symlink_becomes_plain_file(origin, tmp_path, allow_file):
    dest = tmp_path / "clone"
    repo.clone(f"file://{origin}", "main", None, dest)
    link = dest / "skills" / "demo" / "passwd-link"
    assert link.is_file() and not link.is_symlink()
    assert link.read_text() == "/etc/passwd"


def test_file_protocol_blocked_by_default(origin, tmp_path):
    with pytest.raises(repo.RepoError, match="не удалось клонировать"):
        repo.clone(f"file://{origin}", "main", None, tmp_path / "clone")


def test_missing_branch_error_hides_token(origin, tmp_path, monkeypatch):
    # Токен встраивается только в http(s); проверяем scrub на ошибке http-клона.
    url = "https://git.example.invalid/org/skills.git"
    with pytest.raises(repo.RepoError) as exc:
        repo.clone(url, "main", "secret-token", tmp_path / "clone", timeout=20)
    assert "secret-token" not in str(exc.value)
    assert url in str(exc.value)


def test_clone_timeout(tmp_path, monkeypatch):
    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=kwargs["timeout"])

    monkeypatch.setattr(repo.subprocess, "run", slow)
    with pytest.raises(repo.RepoError, match="не уложилось в 5 с"):
        repo.clone("https://git.example.invalid/x.git", "main", None, tmp_path / "c", timeout=5)


def test_clone_timeout_capped_by_deadline(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["timeout"] = kwargs["timeout"]
        raise subprocess.TimeoutExpired(cmd="git", timeout=kwargs["timeout"])

    monkeypatch.setattr(repo.subprocess, "run", fake_run)
    with pytest.raises(repo.RepoError):
        repo.clone("https://git.example.invalid/x.git", "main", None, tmp_path / "c", timeout=10_000)
    assert seen["timeout"] == repo.CLONE_TIMEOUT_SECONDS


def test_measure(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x").write_bytes(b"12345")
    (tmp_path / "y").write_bytes(b"1")
    assert repo.measure(tmp_path) == (2, 6)


def test_git_auth_embeds_token_only_for_https():
    assert git_auth.authenticated_git_url("https://h.invalid/o/r.git", "t/k") == "https://oauth2:t%2Fk@h.invalid/o/r.git"
    assert git_auth.authenticated_git_url("https://h.invalid:8443/r.git", "t") == "https://oauth2:t@h.invalid:8443/r.git"
    assert git_auth.authenticated_git_url("ssh://git@h.invalid/r.git", "t") == "ssh://git@h.invalid/r.git"
    assert git_auth.authenticated_git_url("https://h.invalid/r.git", None) == "https://h.invalid/r.git"


def test_scrub():
    assert repo.scrub("fatal: https://oauth2:x@h/r", "https://oauth2:x@h/r", "https://h/r") == "fatal: https://h/r"
