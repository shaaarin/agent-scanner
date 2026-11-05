# Сканер «Promptfoo red teaming»: Python-обёртка (FastAPI) над CLI
# promptfoo redteam run. Node -- потому что promptfoo это npm-пакет
# (нужен Node >= 22.22, берём LTS 24, как в официальном GitHub Action).
FROM node:24-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Версия promptfoo зафиксирована (та же, что в scanner-promptfoo),
# lifecycle-скрипты пакетов не выполняются.
ARG PROMPTFOO_VERSION=0.123.1
RUN npm install -g --ignore-scripts --no-audit --no-fund \
        --fetch-retries=5 --fetch-retry-maxtimeout=120000 \
        "promptfoo@${PROMPTFOO_VERSION}" \
    && npm cache clean --force

WORKDIR /srv

COPY requirements.txt ./
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir -r requirements.txt
ENV PATH="/venv/bin:$PATH" \
    NODE_NO_WARNINGS=1

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
