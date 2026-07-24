"""Manages the platform's MITM root CA: a self-signed certificate authority
whose private key signs per-host leaf certs on the fly inside `proxy`'s
mitmproxy addon, and whose public cert gets written into the tested agent's
trust store (see pod_manager.py's ca-trust-setup initContainer) so it
accepts those leaf certs as valid.

Generated once and stored as a Kubernetes Secret in a dedicated
`agent-scanner-system` namespace; copied into each scan's namespace on
first use, since k8s Secrets aren't readable across namespaces.
"""
import datetime

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from kubernetes import client as k8s
from kubernetes.client.rest import ApiException

from app.k8s_client import core_v1

CA_SYSTEM_NAMESPACE = "agent-scanner-system"
CA_SECRET_NAME = "agent-scanner-mitm-ca"


def _generate_ca() -> tuple[bytes, bytes]:
    """Self-signed root CA, RSA 2048, ~10y validity. Returns (cert_pem, key_pem)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "agent-scanner MITM root CA")])
    now = datetime.datetime.now(datetime.timezone.utc)

    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return cert_pem, key_pem


def ensure_ca_secret() -> None:
    """Idempotent: generates the CA once and stores it centrally."""
    core = core_v1()
    try:
        core.create_namespace(k8s.V1Namespace(metadata=k8s.V1ObjectMeta(name=CA_SYSTEM_NAMESPACE)))
    except ApiException as exc:
        if exc.status != 409:
            raise

    try:
        core.read_namespaced_secret(CA_SECRET_NAME, CA_SYSTEM_NAMESPACE)
        return
    except ApiException as exc:
        if exc.status != 404:
            raise

    cert_pem, key_pem = _generate_ca()
    secret = k8s.V1Secret(
        metadata=k8s.V1ObjectMeta(name=CA_SECRET_NAME, namespace=CA_SYSTEM_NAMESPACE),
        string_data={"ca.crt": cert_pem.decode(), "ca.key": key_pem.decode()},
    )
    core.create_namespaced_secret(CA_SYSTEM_NAMESPACE, secret)


def ensure_ca_secret_in_namespace(namespace: str) -> None:
    """Copies the central CA secret into a scan's namespace so Pod volumes
    there can mount it (k8s Secrets don't work cross-namespace).
    """
    ensure_ca_secret()
    core = core_v1()

    try:
        core.read_namespaced_secret(CA_SECRET_NAME, namespace)
        return
    except ApiException as exc:
        if exc.status != 404:
            raise

    central = core.read_namespaced_secret(CA_SECRET_NAME, CA_SYSTEM_NAMESPACE)
    secret = k8s.V1Secret(
        metadata=k8s.V1ObjectMeta(name=CA_SECRET_NAME, namespace=namespace),
        data=central.data,  # already base64-encoded, copy as-is
    )
    try:
        core.create_namespaced_secret(namespace, secret)
    except ApiException as exc:
        if exc.status != 409:
            raise
