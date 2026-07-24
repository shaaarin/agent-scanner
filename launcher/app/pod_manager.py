"""Builds the tested agent's Pod spec for transparent MITM interception:
the agent container gets zero platform-aware configuration (no proxy env
vars) -- its own real LLM credentials, however it's configured, just work.
Interception happens via:

  1. a `ca-trust-setup` initContainer that writes a combined CA bundle (the
     init image's own OS default CAs + our MITM root CA, see ca_manager.py)
     into a shared emptyDir, mounted over the agent container's system
     trust-store file so it accepts our on-the-fly leaf certs as valid;
  2. a `net-setup` initContainer (NET_ADMIN) that adds an iptables NAT
     REDIRECT rule sending the agent's outbound HTTPS traffic to the
     `mitm-proxy` sidecar, excluding the sidecar's own uid so its upstream
     connections don't get redirected back into itself;
  3. the `mitm-proxy` sidecar itself (our own `proxy` image, mitmproxy in
     transparent mode), sharing the Pod's network namespace with the agent.

Known limitation: the iptables rule is applied before the sidecar
container starts listening (initContainers necessarily run before regular
containers), so an agent connection attempted in that narrow startup
window will fail -- acceptable for an MVP since real agents typically
don't dial out within the first instant of process start, and most HTTP
clients retry.
"""
import os

from kubernetes import client as k8s
from kubernetes.client.rest import ApiException

from app.ca_manager import CA_SECRET_NAME
from app.host_alias import resolve_host_alias
from app.k8s_client import core_v1

PROXY_IMAGE = os.environ.get("PROXY_IMAGE", "kind-registry:5000/agent-scanner-proxy:latest")
# The mitm-proxy sidecar runs inside the cluster, not Compose -- it needs a
# control-api address actually reachable from there. Deliberately NOT the
# same as launcher's own CONTROL_API_URL: dual-homing control-api itself
# onto the `kind` network made its host-published port flaky (WSL2 quirk),
# so a dedicated forwarder (control-api-mitm-bridge, see docker-compose.yml)
# absorbs that instead.
MITM_CONTROL_API_URL = os.environ.get("MITM_CONTROL_API_URL", "http://control-api-mitm-bridge:8000")
CA_TRUST_IMAGE = os.environ.get("CA_TRUST_IMAGE", "python:3.12-slim")  # matches other images' base, has ca-certificates
NET_SETUP_IMAGE = os.environ.get("NET_SETUP_IMAGE", "alpine:3.19")

MITM_UID = 1000
MITM_LISTEN_PORT = 8443
TRUST_BUNDLE_PATH = "/etc/ssl/certs/ca-certificates.crt"


def _ca_trust_init_container() -> k8s.V1Container:
    return k8s.V1Container(
        name="ca-trust-setup",
        image=CA_TRUST_IMAGE,
        command=["sh", "-c"],
        args=[f"cat {TRUST_BUNDLE_PATH} /mitm-ca/ca.crt > /trust-bundle/ca-certificates.crt"],
        volume_mounts=[
            k8s.V1VolumeMount(name="trust-bundle", mount_path="/trust-bundle"),
            k8s.V1VolumeMount(name="mitm-ca", mount_path="/mitm-ca", read_only=True),
        ],
    )


def _net_setup_init_container() -> k8s.V1Container:
    rule = (
        f"iptables -t nat -A OUTPUT -p tcp --dport 443 "
        f"-m owner ! --uid-owner {MITM_UID} -j REDIRECT --to-port {MITM_LISTEN_PORT}"
    )
    return k8s.V1Container(
        name="net-setup",
        image=NET_SETUP_IMAGE,
        command=["sh", "-c"],
        args=[f"apk add --no-cache iptables >/dev/null && {rule}"],
        security_context=k8s.V1SecurityContext(capabilities=k8s.V1Capabilities(add=["NET_ADMIN"])),
    )


def _mitm_sidecar_container(session_id: str) -> k8s.V1Container:
    env = [
        k8s.V1EnvVar(name="SESSION_ID", value=session_id),
        k8s.V1EnvVar(name="CONTROL_API_URL", value=MITM_CONTROL_API_URL),
        k8s.V1EnvVar(name="MITM_MODE", value="transparent"),
        k8s.V1EnvVar(name="MITM_LISTEN_PORT", value=str(MITM_LISTEN_PORT)),
    ]
    return k8s.V1Container(
        name="mitm-proxy",
        image=PROXY_IMAGE,
        env=env,
        image_pull_policy="Always",
        security_context=k8s.V1SecurityContext(run_as_user=MITM_UID),
        volume_mounts=[k8s.V1VolumeMount(name="mitm-ca", mount_path="/mitm-ca", read_only=True)],
    )


def _agent_container(agent_config: dict, image: str) -> k8s.V1Container:
    env_vars = {
        **agent_config.get("env_vars", {}),
        "SSL_CERT_FILE": TRUST_BUNDLE_PATH,
        "REQUESTS_CA_BUNDLE": TRUST_BUNDLE_PATH,
        "NODE_EXTRA_CA_CERTS": TRUST_BUNDLE_PATH,
    }
    env = [k8s.V1EnvVar(name=k, value=v) for k, v in env_vars.items()]

    resources = None
    res_cfg = agent_config.get("resources")
    if res_cfg:
        resources = k8s.V1ResourceRequirements(requests=res_cfg, limits=res_cfg)

    ports = None
    if agent_config.get("api_port"):
        ports = [k8s.V1ContainerPort(container_port=agent_config["api_port"])]

    return k8s.V1Container(
        name="agent",
        image=image,
        command=agent_config.get("entrypoint") or None,
        env=env,
        resources=resources,
        ports=ports,
        image_pull_policy="Always",
        volume_mounts=[
            k8s.V1VolumeMount(
                name="trust-bundle",
                mount_path=TRUST_BUNDLE_PATH,
                sub_path="ca-certificates.crt",
            )
        ],
    )


def _pod_manifest(pod_name: str, namespace: str, agent_config: dict, session_id: str, image: str) -> k8s.V1Pod:
    volumes = [
        k8s.V1Volume(name="trust-bundle", empty_dir=k8s.V1EmptyDirVolumeSource()),
        k8s.V1Volume(name="mitm-ca", secret=k8s.V1SecretVolumeSource(secret_name=CA_SECRET_NAME)),
    ]

    # The mitm-proxy sidecar calls MITM_CONTROL_API_URL directly -- if
    # that's a Docker Compose container name (the control-api-mitm-bridge
    # forwarder), the cluster's own CoreDNS can't resolve it, same gap as
    # build.py's git-clone step.
    host_alias = resolve_host_alias(MITM_CONTROL_API_URL)

    pod_spec = k8s.V1PodSpec(
        restart_policy="Never",
        init_containers=[_ca_trust_init_container(), _net_setup_init_container()],
        containers=[_agent_container(agent_config, image), _mitm_sidecar_container(session_id)],
        volumes=volumes,
        host_aliases=[host_alias] if host_alias else None,
    )
    labels = {"app": "agent-scanner-target", "agent-config-id": str(agent_config["id"])}
    return k8s.V1Pod(
        metadata=k8s.V1ObjectMeta(name=pod_name, namespace=namespace, labels=labels), spec=pod_spec
    )


def launch_pod(namespace: str, agent_config: dict, session_id: str, image: str) -> str:
    core = core_v1()
    pod_name = f"agent-{agent_config['id']}"
    manifest = _pod_manifest(pod_name, namespace, agent_config, session_id, image)
    try:
        core.create_namespaced_pod(namespace=namespace, body=manifest)
    except ApiException as exc:
        if exc.status != 409:
            raise
    return pod_name


def ensure_agent_service(namespace: str, agent_config: dict) -> int | None:
    """If the AgentConfig declares an api_port, ensures a NodePort Service
    selecting the agent Pod (by its agent-config-id label) exists and
    returns the allocated nodePort. NodePort, not ClusterIP, because a
    Pod's ClusterIP is not reachable from interactor's/the web UI's Docker
    Compose containers (different network layers) -- see docs/architecture.md.
    Returns None if api_port isn't set.
    """
    api_port = agent_config.get("api_port")
    if not api_port:
        return None

    core = core_v1()
    service_name = f"agent-{agent_config['id']}-svc"
    try:
        existing = core.read_namespaced_service(service_name, namespace)
        return existing.spec.ports[0].node_port
    except ApiException as exc:
        if exc.status != 404:
            raise

    service = k8s.V1Service(
        metadata=k8s.V1ObjectMeta(name=service_name, namespace=namespace),
        spec=k8s.V1ServiceSpec(
            type="NodePort",
            selector={"app": "agent-scanner-target", "agent-config-id": str(agent_config["id"])},
            ports=[k8s.V1ServicePort(port=api_port, target_port=api_port)],
        ),
    )
    created = core.create_namespaced_service(namespace=namespace, body=service)
    return created.spec.ports[0].node_port


def node_address() -> str | None:
    """The k8s node's own container name (e.g. `agent-scanner-control-plane`
    for a single-node `kind` cluster) -- reachable from launcher/interactor
    since they're on the same `kind` Docker network. Returns the first
    node's name; fine for the single-control-plane-node local dev setup
    this platform is built around.
    """
    core = core_v1()
    nodes = core.list_node().items
    return nodes[0].metadata.name if nodes else None


def pod_status(namespace: str, pod_name: str) -> str:
    core = core_v1()
    try:
        pod = core.read_namespaced_pod_status(pod_name, namespace)
    except ApiException as exc:
        if exc.status == 404:
            return "not_found"
        raise
    return pod.status.phase
