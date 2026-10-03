"""Builds the tested agent's image in-cluster from its git repo: a
git-clone init container populates a shared emptyDir, then Kaniko builds
from that local directory context and pushes to the local registry.
Deliberately not using Kaniko's own `git://` context support -- a plain
`git clone` generalizes trivially to private repos (AgentConfig.git_access_token,
embedded into the clone URL by app/git_auth.py) without touching the
Kaniko step.
"""
import os
import shlex
import time

from kubernetes import client as k8s
from kubernetes.client.rest import ApiException

from app.git_auth import authenticated_git_url
from app.host_alias import resolve_host_alias
from app.k8s_client import batch_v1

REGISTRY = os.environ.get("AGENT_IMAGE_REGISTRY", "kind-registry:5000")
KANIKO_IMAGE = os.environ.get("KANIKO_IMAGE", "gcr.io/kaniko-project/executor:latest")
GIT_CLONE_IMAGE = os.environ.get("GIT_CLONE_IMAGE", "alpine/git:latest")
DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("BUILD_TIMEOUT_SECONDS", "300"))


class BuildError(Exception):
    pass


def image_tag(agent_config_id: int, git_ref: str) -> str:
    safe_ref = "".join(c if c.isalnum() or c in "-_." else "-" for c in git_ref)
    return f"{REGISTRY}/agents/{agent_config_id}:{safe_ref}"


def _build_job_manifest(job_name: str, namespace: str, agent_config: dict) -> k8s.V1Job:
    # Build context is always the repo root -- dockerfile_path is a path to
    # the Dockerfile itself (e.g. "Dockerfile" or "agent/Dockerfile"),
    # resolved by Kaniko relative to that same root, matching normal Docker
    # build semantics (COPY paths in the Dockerfile are relative to the
    # context root, not the Dockerfile's own location).
    dockerfile_path = agent_config.get("dockerfile_path") or "Dockerfile"
    destination = image_tag(agent_config["id"], agent_config["git_ref"])
    clone_url = authenticated_git_url(agent_config["git_repo_url"], agent_config.get("git_access_token"))

    clone_container = k8s.V1Container(
        name="clone",
        image=GIT_CLONE_IMAGE,
        command=["sh", "-c"],
        # Ветка и адрес -- из AgentConfig, в shell-команду только через quote.
        args=[
            f"git clone --branch {shlex.quote(agent_config['git_ref'])} --depth 1 "
            f"{shlex.quote(clone_url)} /workspace/src"
        ],
        volume_mounts=[k8s.V1VolumeMount(name="workspace", mount_path="/workspace")],
    )

    kaniko_container = k8s.V1Container(
        name="kaniko",
        image=KANIKO_IMAGE,
        args=[
            "--context=dir:///workspace/src",
            f"--dockerfile={dockerfile_path}",
            f"--destination={destination}",
            "--insecure",
            "--skip-tls-verify",
        ],
        volume_mounts=[k8s.V1VolumeMount(name="workspace", mount_path="/workspace")],
    )

    host_alias = resolve_host_alias(agent_config["git_repo_url"])

    pod_spec = k8s.V1PodSpec(
        restart_policy="Never",
        init_containers=[clone_container],
        containers=[kaniko_container],
        volumes=[k8s.V1Volume(name="workspace", empty_dir=k8s.V1EmptyDirVolumeSource())],
        host_aliases=[host_alias] if host_alias else None,
    )

    return k8s.V1Job(
        metadata=k8s.V1ObjectMeta(name=job_name, namespace=namespace),
        spec=k8s.V1JobSpec(backoff_limit=0, template=k8s.V1PodTemplateSpec(spec=pod_spec)),
    )


def run_build(namespace: str, agent_config: dict, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> tuple[str, str]:
    """Creates the build Job and blocks until it succeeds or fails.
    Returns (job_name, built_image). Blocking within the request is a known
    MVP simplification -- a background-job/webhook model would be needed at
    real scale.
    """
    batch = batch_v1()
    job_name = f"build-{agent_config['id']}"
    manifest = _build_job_manifest(job_name, namespace, agent_config)

    try:
        batch.create_namespaced_job(namespace=namespace, body=manifest)
    except ApiException as exc:
        if exc.status != 409:
            raise BuildError(f"failed to create build job: {exc}") from exc

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        job = batch.read_namespaced_job_status(job_name, namespace)
        if job.status.succeeded:
            return job_name, image_tag(agent_config["id"], agent_config["git_ref"])
        if job.status.failed:
            raise BuildError(f"build job {job_name} failed -- check `kubectl logs -n {namespace} job/{job_name}`")
        time.sleep(3)

    raise BuildError(f"build job {job_name} did not complete within {timeout_seconds}s")
