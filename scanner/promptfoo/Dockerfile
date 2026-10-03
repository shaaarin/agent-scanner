# Сканер «Анализ кода»: Python-обёртка (FastAPI) над CLI promptfoo code-scans.
# Node -- потому что promptfoo это npm-пакет (нужен Node >= 22.22, берём LTS 24,
# как в официальном GitHub Action promptfoo).
FROM node:24-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Версии зафиксированы, lifecycle-скрипты пакетов не выполняются -- так же
# ставит promptfoo его официальный GitHub Action. Пакеты ставятся глобально,
# вне сканируемых репозиториев.
#
# server-filesystem -- MCP-сервер, через который облако Promptfoo читает файлы
# репозитория. promptfoo 0.123.x запускает его через `npx -y` (скачивание на
# каждом скане), поэтому ставим его заранее, а вызов перехватывает bin/npx.
ARG PROMPTFOO_VERSION=0.123.1
ARG MCP_FILESYSTEM_VERSION=2026.8.31
RUN npm install -g --ignore-scripts --no-audit --no-fund \
        --fetch-retries=5 --fetch-retry-maxtimeout=120000 \
        "promptfoo@${PROMPTFOO_VERSION}" \
        "@modelcontextprotocol/server-filesystem@${MCP_FILESYSTEM_VERSION}" \
    && npm cache clean --force

# Обёртка npx: разрешает только запуск установленного выше filesystem-MCP.
COPY bin/npx /opt/agent-scanner/bin/npx
RUN chmod 0755 /opt/agent-scanner/bin/npx

WORKDIR /srv

COPY requirements.txt ./
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir -r requirements.txt
ENV PATH="/opt/agent-scanner/bin:/venv/bin:$PATH" \
    NODE_NO_WARNINGS=1

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
