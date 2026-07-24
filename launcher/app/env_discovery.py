"""Reads an agent repo's own declared env-var defaults (a `.env.example`-
style file, path given by `AgentConfig.env_example_path`) so a user doesn't
have to manually inspect a third-party agent's source/docs to know what
env vars it expects. This is a quick **local** shallow clone in launcher's
own container -- separate from, and ahead of, the actual in-cluster
git-clone+Kaniko build Job (which only needs to run once the full env_vars
dict is already known).
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.git_auth import authenticated_git_url


class EnvDiscoveryError(Exception):
    pass


def _parse_env_file(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def discover_env_defaults(
    git_repo_url: str, git_ref: str, env_example_path: str, access_token: str | None = None
) -> dict[str, str]:
    """Shallow-clones the repo to a temp dir and parses env_example_path's
    KEY=value lines. Returns {} (never raises) if the clone or the file
    itself fails -- env_example_path is a convenience, not a hard
    requirement, so a missing/renamed file shouldn't block a launch.
    """
    tmpdir = tempfile.mkdtemp(prefix="agent-scanner-env-discovery-")
    try:
        clone_url = authenticated_git_url(git_repo_url, access_token)
        result = subprocess.run(
            ["git", "clone", "--branch", git_ref, "--depth", "1", clone_url, tmpdir],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            stderr = result.stderr.replace(clone_url, git_repo_url) if access_token else result.stderr
            print(f"[env_discovery] clone failed, skipping env-defaults discovery: {stderr}")
            return {}

        env_file = Path(tmpdir) / env_example_path
        if not env_file.is_file():
            print(f"[env_discovery] {env_example_path} not found in repo, skipping")
            return {}

        return _parse_env_file(env_file.read_text())
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"[env_discovery] failed, skipping env-defaults discovery: {exc}")
        return {}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def merge_env_defaults(env_vars: dict[str, str], discovered: dict[str, str]) -> dict[str, str]:
    """Repo-declared defaults fill in only keys the AgentConfig doesn't
    already set -- explicit config always wins (e.g. a real API key
    overriding the example's placeholder).
    """
    merged = dict(discovered)
    merged.update(env_vars)
    return merged
