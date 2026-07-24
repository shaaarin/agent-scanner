"""Resolves a URL's host from launcher's own network context (attached to
both the default Compose network and the `kind` network) and pins it as a
k8s hostAlias, for hosts the cluster's own CoreDNS can't resolve -- Docker
Compose container names like `control-api` or `git-server`. Harmless no-op
for hosts that resolve normally through the cluster's own DNS (e.g. a real
git provider or LLM API).
"""
import socket
from urllib.parse import urlparse

from kubernetes import client as k8s


def resolve_host_alias(url: str) -> k8s.V1HostAlias | None:
    host = urlparse(url).hostname
    if not host:
        return None
    try:
        ip = socket.gethostbyname(host)
    except socket.gaierror:
        return None
    return k8s.V1HostAlias(ip=ip, hostnames=[host])
