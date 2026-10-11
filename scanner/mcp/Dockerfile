FROM python:3.13-slim
WORKDIR /srv
RUN pip install --no-cache-dir fastapi 'uvicorn[standard]' httpx 'mcp==1.30.0'
# Separate dependency environments keep upstream scanners independent.
RUN python -m venv /opt/cisco && /opt/cisco/bin/pip install --no-cache-dir cisco-ai-mcp-scanner==4.8.6
RUN python -m venv /opt/snyk && /opt/snyk/bin/pip install --no-cache-dir snyk-agent-scan==0.6.8
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/semgrep && /opt/semgrep/bin/pip install --no-cache-dir semgrep==1.180.0
RUN python -m venv /opt/mcpradar && /opt/mcpradar/bin/pip install --no-cache-dir mcpradar==1.0.0rc4
COPY rules ./rules
COPY app ./app
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
