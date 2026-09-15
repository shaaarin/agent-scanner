"""The DeepTeam `model_callback`: bridges DeepTeam's synchronous callback
into the tested agent's own external API. DeepTeam passes one attack payload
at a time; each payload becomes a fresh conversation with the agent so
attacks don't leak context into each other.

Both wire contracts mirror `interactor/app/target_client.py` -- same
`api_config` / `langgraph_config` shapes, but synchronous since DeepTeam runs
in a plain thread.
"""
from typing import Any, Optional

import httpx

_DEFAULT_REQUEST_BODY_TEMPLATE = {"message": "{{message}}"}
_DEFAULT_RESPONSE_FIELD = "reply"


def _substitute(node: Any, message: str) -> Any:
    if isinstance(node, str):
        return node.replace("{{message}}", message)
    if isinstance(node, dict):
        return {k: _substitute(v, message) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute(v, message) for v in node]
    return node


def _extract(data: Any, path: str) -> Any:
    current = data
    for segment in path.split("."):
        if isinstance(current, list):
            current = current[int(segment)]
        elif isinstance(current, dict):
            current = current[segment]
        else:
            raise KeyError(f"cannot descend into {segment!r} of non-container value")
    return current


def _send_via_api(api_config: dict, message: str, client: httpx.Client) -> str:
    url = api_config["url"]
    method = api_config.get("method", "POST").upper()
    body_template = api_config.get("request_body_template", _DEFAULT_REQUEST_BODY_TEMPLATE)
    response_field = api_config.get("response_field", _DEFAULT_RESPONSE_FIELD)
    headers = api_config.get("headers") or {}
    body = _substitute(body_template, message)

    if method == "GET":
        resp = client.get(url, params=body, headers=headers)
    else:
        resp = client.request(method, url, json=body, headers=headers)
    resp.raise_for_status()
    try:
        return str(_extract(resp.json(), response_field))
    except (ValueError, KeyError, IndexError, TypeError):
        return resp.text


def _send_via_langgraph(langgraph_config: dict, message: str) -> str:
    base_url = langgraph_config["base_url"].rstrip("/")
    assistant_id = langgraph_config.get("assistant_id", "agent")
    headers = {}
    if langgraph_config.get("api_key"):
        headers["X-Api-Key"] = langgraph_config["api_key"]

    with httpx.Client(base_url=base_url, headers=headers, timeout=120.0) as client:
        thread = client.post("/threads", json={})
        thread.raise_for_status()
        thread_id = thread.json()["thread_id"]
        try:
            resp = client.post(
                f"/threads/{thread_id}/runs/wait",
                json={
                    "assistant_id": assistant_id,
                    "input": {"messages": [{"role": "user", "content": message}]},
                },
            )
            resp.raise_for_status()
            messages = resp.json().get("messages") or []
            for msg in reversed(messages):
                # LangGraph emits its own message schema: `type` is
                # "human"/"ai"/"tool" and `role` is often absent.
                if msg.get("type") in ("ai", "assistant") or msg.get("role") in ("assistant", "ai"):
                    return str(msg.get("content", ""))
            return ""
        finally:
            try:
                client.delete(f"/threads/{thread_id}")
            except httpx.HTTPError:
                pass


def build_model_callback(agent_config: dict):
    """Returns a `(input, turns=None) -> str` callback for `deepteam.red_team`.
    `turns` is accepted (so DeepTeam passes multi-turn context) but ignored:
    the UI only seeds single-turn attacks today.
    """
    mode = agent_config.get("interaction_mode")
    if mode == "langgraph":
        langgraph_config = agent_config.get("langgraph_config") or {}
        if not langgraph_config.get("base_url"):
            raise RuntimeError(
                "у агента не задан langgraph_config.base_url -- укажите api_port в конфиге агента, "
                "чтобы launcher автоматически пробросил адрес"
            )

        def callback(input: str, turns: Optional[list] = None) -> str:
            return _send_via_langgraph(langgraph_config, input)

        return callback

    if mode == "api":
        api_config = agent_config.get("api_config") or {}
        if not api_config.get("url"):
            raise RuntimeError("у агента не задан api_config.url -- укажите api_port, чтобы launcher пробросил адрес")

        def callback(input: str, turns: Optional[list] = None) -> str:
            with httpx.Client(timeout=120.0) as client:
                return _send_via_api(api_config, input, client)

        return callback

    raise RuntimeError(f"interaction_mode={mode!r} не поддерживает интерактивное сканирование")
