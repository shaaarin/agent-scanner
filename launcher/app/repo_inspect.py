"""Interactive git-repo introspection for the AgentConfigs web UI's creation
wizard: list branches, then discover Dockerfile/`.env.example` candidates
for a chosen branch, before any `AgentConfig` exists. Same shallow-clone
approach as `env_discovery.py`, but that module runs at actual `/launch`
time against an already-known `env_example_path` and silently skips on
failure (a missing file there is a soft convenience); here, failure IS the
signal the user needs (wrong URL/branch/token), so both functions raise.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.env_discovery import _parse_env_file
from app.git_auth import authenticated_git_url

LS_REMOTE_TIMEOUT_SECONDS = 20
CLONE_TIMEOUT_SECONDS = 60

DOCKERFILE_SKIP_DIRS = {".git"}


class RepoInspectError(Exception):
    pass


def _scrub(text: str, clone_url: str, git_repo_url: str) -> str:
    return text.replace(clone_url, git_repo_url) if clone_url != git_repo_url else text


def list_branches(git_repo_url: str, access_token: str | None = None) -> list[str]:
    """`git ls-remote --heads` -- no clone needed, just lists remote refs."""
    clone_url = authenticated_git_url(git_repo_url, access_token)
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", clone_url],
            capture_output=True,
            text=True,
            timeout=LS_REMOTE_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RepoInspectError(f"failed to reach repository: {exc}") from exc

    if result.returncode != 0:
        raise RepoInspectError(_scrub(result.stderr.strip(), clone_url, git_repo_url) or "git ls-remote failed")

    branches: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or "refs/heads/" not in line:
            continue
        branches.append(line.split("refs/heads/", 1)[1])

    if not branches:
        raise RepoInspectError("repository has no branches, or is unreachable with the given URL/token")

    def _sort_key(name: str) -> tuple[int, str]:
        return (0 if name in ("main", "master") else 1, name)

    return sorted(branches, key=_sort_key)


def _is_dockerfile(name: str) -> bool:
    return name == "Dockerfile" or name.endswith(".Dockerfile")


def _is_env_example(name: str) -> bool:
    return name == ".env.example" or (name.startswith(".env.") and name.endswith(".example"))


def inspect_repo(git_repo_url: str, git_ref: str, access_token: str | None = None) -> dict:
    """Shallow-clones `git_ref` and returns
    {"dockerfiles": [...], "env_examples": {"<path>": {"KEY": "value", ...}, ...}}
    (paths relative to the repo root). Every discovered `.env.example`
    candidate is parsed immediately so the wizard needs no third round trip.
    """
    tmpdir = tempfile.mkdtemp(prefix="agent-scanner-repo-inspect-")
    clone_url = authenticated_git_url(git_repo_url, access_token)
    try:
        result = subprocess.run(
            ["git", "clone", "--branch", git_ref, "--depth", "1", clone_url, tmpdir],
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise RepoInspectError(_scrub(result.stderr.strip(), clone_url, git_repo_url) or "git clone failed")

        root = Path(tmpdir)
        dockerfiles: list[str] = []
        env_examples: dict[str, dict[str, str]] = {}

        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if DOCKERFILE_SKIP_DIRS & set(path.relative_to(root).parts):
                continue
            rel = path.relative_to(root).as_posix()
            if _is_dockerfile(path.name):
                dockerfiles.append(rel)
            elif _is_env_example(path.name):
                env_examples[rel] = _parse_env_file(path.read_text(errors="ignore"))

        return {"dockerfiles": dockerfiles, "env_examples": env_examples}
    except subprocess.TimeoutExpired as exc:
        raise RepoInspectError(f"clone timed out: {exc}") from exc
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
