FROM python:3.12-slim

WORKDIR /srv

RUN pip install --no-cache-dir fastapi "uvicorn[standard]"

COPY echo_agent.py ./

EXPOSE 8000
CMD ["uvicorn", "echo_agent:app", "--host", "0.0.0.0", "--port", "8000"]
