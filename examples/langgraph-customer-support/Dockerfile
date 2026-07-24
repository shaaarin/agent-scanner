# A real LangGraph agent, served by the actual `langgraph dev` local API
# server (langgraph-cli's in-memory runtime) -- not a hand-rolled stand-in
# for the LangGraph Platform REST surface. Exposes exactly the
# threads/runs API interactor/app/target_client.LangGraphSession already
# speaks: POST /threads, POST /threads/{id}/runs/wait, DELETE /threads/{id}.
FROM python:3.12-slim

WORKDIR /srv

COPY pyproject.toml ./
RUN pip install --no-cache-dir "langgraph-cli[inmem]" langgraph langchain-openai

COPY graph.py langgraph.json ./

EXPOSE 8123
CMD ["langgraph", "dev", "--host", "0.0.0.0", "--port", "8123", "--no-browser"]
