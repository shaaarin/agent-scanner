from kubernetes import client as k8s
from kubernetes.client.rest import ApiException

from app.k8s_client import core_v1


def ensure_namespace(namespace: str) -> None:
    core = core_v1()
    try:
        core.create_namespace(k8s.V1Namespace(metadata=k8s.V1ObjectMeta(name=namespace)))
    except ApiException as exc:
        if exc.status != 409:  # already exists
            raise


def delete_namespace(namespace: str) -> None:
    core = core_v1()
    try:
        core.delete_namespace(namespace)
    except ApiException as exc:
        if exc.status != 404:
            raise
