FROM python:3.12-slim

WORKDIR /srv

RUN pip install --no-cache-dir httpx

COPY agent.py ./

CMD ["python", "agent.py"]
