FROM python:3.12-slim

WORKDIR /srv

COPY pyproject.toml ./
RUN pip install --no-cache-dir mitmproxy httpx deepteam

COPY app ./app
COPY addon.py ./addon.py
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x docker-entrypoint.sh && chmod -R a+rwX /srv

# Runs as a non-root uid at deploy time (pod_manager.py sets MITM_UID=1000)
# so the net-setup initContainer's iptables rule can exclude this
# container's own outbound traffic by uid.
EXPOSE 8443
ENTRYPOINT ["./docker-entrypoint.sh"]
