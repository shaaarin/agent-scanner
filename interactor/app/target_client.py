from typing import Any

import httpx

_DEFAULT_REQUEST_BODY_TEMPLATE = {"message": "{{message}}"}
_DEFAULT_RESPONSE_FIELD = "reply"


def _substitute(node: Any, message: str) -> Any:
    """Recursively replaces the "{{message}}" placeholder in string values
    of a JSON-shaped request body template with the interactor's message.
    """
    if isinstance(node, str):
        return node.replace("{{message}}", message)
    if isinstance(node, dict):
        return {k: _substitute(v, message) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute(v, message) for v in node]
    return node


def _extract(data: Any, path: str) -> Any:
    """Dot-path extraction into a JSON response, e.g. "reply" or
    "data.0.text" (numeric segments index into lists).
    """
    current = data
    for segment in path.split("."):
        if isinstance(current, list):
            current = current[int(segment)]
        elif isinstance(current, dict):
            current = current[segment]
        else:
            raise KeyError(f"cannot descend into {segment!r} of non-container value")
    return current


async def send_via_api(api_config: dict, message: str) -> str:
    """Configurable REST wire contract for interaction_mode=api target
    agents: POSTs (or GETs) `request_body_template` with "{{message}}"
    substituted for the interactor's turn, to `api_config['url']`, and
    reads the reply out of the JSON response at `response_field` (a
    dot-path, e.g. "reply" or "data.0.text"). Defaults to the simple
    {"message": ...} / "reply" shape when not specified, and falls back to
    the raw response body if extraction fails.
    """
    url = api_config["url"]
    method = api_config.get("method", "POST").upper()
    body_template = api_config.get("request_body_template", _DEFAULT_REQUEST_BODY_TEMPLATE)
    response_field = api_config.get("response_field", _DEFAULT_RESPONSE_FIELD)
    headers = api_config.get("headers") or {}
    body = _substitute(body_template, message)

    async with httpx.AsyncClient(timeout=30.0) as client:
        if method == "GET":
            resp = await client.get(url, params=body, headers=headers)
        else:
            resp = await client.request(method, url, json=body, headers=headers)
    resp.raise_for_status()

    try:
        data = resp.json()
        return str(_extract(data, response_field))
    except (ValueError, KeyError, IndexError, TypeError):
        return resp.text


class LangGraphSession:
    """A persistent conversation with a LangGraph Platform / LangGraph API
    SDK-compatible agent: one thread for the whole interactor /run call
    (created via POST /threads), each turn sent via
    POST /threads/{thread_id}/runs/wait -- "one persistent session per run,
    not a fresh one per turn".
    """

    def __init__(self, langgraph_config: dict):
        self.base_url = langgraph_config["base_url"].rstrip("/")
        self.assistant_id = langgraph_config.get("assistant_id", "agent")
        headers = {}
        if langgraph_config.get("api_key"):
            headers["X-Api-Key"] = langgraph_config["api_key"]
        self.client = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=60.0)
        self.thread_id: str | None = None

    async def start(self, existing_thread_id: str | None = None) -> None:
        """Attaches to `existing_thread_id` if given (continuing a branch
        forward -- no new thread created), otherwise creates a fresh thread
        (a new branch to replay into). See generator/app/tree_engine.py.
        """
        if existing_thread_id is not None:
            self.thread_id = existing_thread_id
            return
        resp = await self.client.post("/threads", json={})
        resp.raise_for_status()
        self.thread_id = resp.json()["thread_id"]

    async def send(self, message: str) -> str:
        resp = await self.client.post(
            f"/threads/{self.thread_id}/runs/wait",
            json={
                "assistant_id": self.assistant_id,
                "input": {"messages": [{"role": "user", "content": message}]},
            },
        )
        resp.raise_for_status()
        body = resp.json()
        messages = body.get("messages") or []
        for msg in reversed(messages):
            if msg.get("role") in ("assistant", "ai"):
                return str(msg.get("content", ""))
        return ""

    async def close(self, delete_thread: bool = True) -> None:
        """`delete_thread=False` just closes this object's own httpx client
        without deleting the thread server-side -- used by /session/turn,
        where the thread must survive to be resumed by a later call (each
        call gets its own LangGraphSession instance, since a single HTTP
        request to `interactor` doesn't persist Python objects across
        separate calls).
        """
        if delete_thread and self.thread_id:
            try:
                await self.client.delete(f"/threads/{self.thread_id}")
            except httpx.HTTPError:
                pass
        await self.client.aclose()
