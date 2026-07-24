"""Embeds a Personal Access Token into an HTTPS git URL for private-repo
clones (`https://<token>@host/org/repo.git`), the convention GitHub/GitLab/
Bitbucket all accept for PAT-based auth over HTTPS. Used by both build.py's
in-cluster git-clone init container and env_discovery.py's local shallow
clone, so both build sources agree on how a private repo gets authenticated.

Known, accepted MVP tech debt (same posture as LLMModel.api_key -- plain
text, not encrypted at rest): the token ends up as a literal argument to
`git clone` inside the build Job's init container, so a clone *failure*
there will have git echo the full authenticated URL into that container's
logs (`kubectl logs .../clone`), visible to anyone with log access to the
scan namespace. Not solved in this pass -- a k8s Secret + git credential
helper would avoid it, at real added complexity.
"""
from urllib.parse import urlparse, urlunparse


def authenticated_git_url(git_repo_url: str, access_token: str | None) -> str:
    """No-op for non-HTTP(S) URLs (e.g. the platform's own git:// test
    servers, or ssh:// remotes) or when no token is set.
    """
    if not access_token:
        return git_repo_url
    parsed = urlparse(git_repo_url)
    if parsed.scheme not in ("http", "https"):
        return git_repo_url

    netloc = f"{access_token}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))
