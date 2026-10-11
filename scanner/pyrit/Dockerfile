FROM python:3.12-slim
WORKDIR /srv
# base2048 (транзитивная зависимость pyrit) не имеет готового wheel под arm64
# и собирается из исходников -- нужен Rust.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cargo \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
