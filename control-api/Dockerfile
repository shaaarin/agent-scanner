FROM python:3.12-slim

WORKDIR /srv

COPY pyproject.toml ./
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" sqlmodel httpx pyyaml alembic python-multipart "psycopg[binary]" itsdangerous pika==1.3.2

COPY app ./app
COPY scripts ./scripts
COPY alembic.ini ./alembic.ini

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
