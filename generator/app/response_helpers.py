"""Read-only helpers for OpenAI-shaped chat-completion request/response
bodies. Ported from proxy/app/openai_provider.py -- proxy no longer performs
detection itself, so these now run here against a directly-called LLM
response instead of an intercepted one.
"""


def iter_tool_calls(response_body: dict) -> list[dict]:
    choices = response_body.get("choices") or []
    if not choices:
        return []
    message = choices[0].get("message", {})
    return message.get("tool_calls") or []


def get_response_text(response_body: dict) -> str:
    choices = response_body.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message", {})
    return message.get("content") or ""


def iter_tool_result_texts(request_body: dict) -> list[str]:
    """Content strings from prior `role: tool` messages in the conversation
    history -- i.e. what tools already returned to the agent in this thread.
    """
    texts = []
    for message in request_body.get("messages", []):
        if message.get("role") == "tool":
            content = message.get("content")
            if isinstance(content, str):
                texts.append(content)
    return texts
