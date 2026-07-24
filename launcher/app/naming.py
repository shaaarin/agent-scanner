import re


def sanitize_k8s_name(value: str, prefix: str = "") -> str:
    """DNS-1123 label rules: lowercase alphanumeric + hyphen, <=63 chars,
    no leading/trailing hyphen.
    """
    slug = re.sub(r"[^a-z0-9-]", "-", value.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    name = f"{prefix}{slug}" if prefix else slug
    return name[:63].rstrip("-")


def namespace_for_session(session_id: str) -> str:
    return sanitize_k8s_name(session_id, prefix="scan-")
