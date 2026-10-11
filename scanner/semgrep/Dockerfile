# Сканер «Анализ AI-кода»: локальный semgrep по склонированному репозиторию
# агента. Код не покидает платформу, внешние ключи не нужны; без kind и
# launcher, как scanner-promptfoo.
FROM python:3.13-slim
WORKDIR /srv

RUN pip install --no-cache-dir fastapi 'uvicorn[standard]' httpx pyyaml

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Semgrep в отдельном venv: тяжёлая зависимость со своим деревом пакетов --
# так же изолированы движки scanner-mcp. Версия зафиксирована (совпадает
# с движком SAST scanner-mcp).
RUN python -m venv /opt/semgrep && /opt/semgrep/bin/pip install --no-cache-dir semgrep==1.180.0

COPY rules ./rules
COPY app ./app

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
