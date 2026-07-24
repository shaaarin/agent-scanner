FROM python:3.12-slim

WORKDIR /srv

# git: env_discovery.py does a quick local shallow clone to read an agent
# repo's env.example, ahead of (and separate from) the actual in-cluster
# git-clone+Kaniko build Job.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" httpx kubernetes cryptography

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
