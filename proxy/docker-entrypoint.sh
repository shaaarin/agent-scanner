#!/bin/sh
# Loads the platform's own MITM root CA (mounted from the ca_manager.py-
# managed Secret at /mitm-ca) as mitmproxy's own CA, so the leaf certs it
# generates on the fly chain back to the exact CA the agent's trust store
# was overwritten with by pod_manager.py's ca-trust-setup initContainer --
# not mitmproxy's own randomly-generated default CA.
set -e

CONFDIR="${MITM_CONFDIR:-/tmp/mitm-confdir}"
mkdir -p "$CONFDIR"

if [ -f /mitm-ca/ca.crt ] && [ -f /mitm-ca/ca.key ]; then
  cat /mitm-ca/ca.crt /mitm-ca/ca.key > "$CONFDIR/mitmproxy-ca.pem"
fi

MODE="${MITM_MODE:-transparent}"
LISTEN_PORT="${MITM_LISTEN_PORT:-8443}"

exec mitmdump \
  -s addon.py \
  --set confdir="$CONFDIR" \
  --mode "$MODE" \
  --listen-port "$LISTEN_PORT" \
  --set ssl_insecure=true
