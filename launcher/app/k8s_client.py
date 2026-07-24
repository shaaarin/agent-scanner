import os

from kubernetes import client, config

_loaded = False


def _ensure_loaded() -> None:
    global _loaded
    if not _loaded:
        config.load_kube_config(config_file=os.environ.get("KUBECONFIG"))
        _loaded = True


def core_v1() -> client.CoreV1Api:
    _ensure_loaded()
    return client.CoreV1Api()


def batch_v1() -> client.BatchV1Api:
    _ensure_loaded()
    return client.BatchV1Api()
