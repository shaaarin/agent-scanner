"""Applies an InjectionTemplate's mode/payload to a captured request body.

Ported from proxy/app/openai_provider.py + proxy/app/injector.py: the fuzz
and tree engines no longer inject into live intercepted traffic (proxy is
capture-only now) -- they mutate a captured `messages` array in place and
send it directly to the tested LLM. Only request-side targets make sense
here (user_message/tool_result/system_prompt) -- there's no live response to
mutate before it "reaches" anyone; the raw completion is read back as-is for
detection.
"""
from typing import Optional

TARGET_TO_ROLE = {
    "user_message": "user",
    "tool_result": "tool",
    "system_prompt": "system",
}


def _find_last_message(messages: list[dict], role: str) -> Optional[dict]:
    for message in reversed(messages):
        if message.get("role") == role:
            return message
    return None


def apply_text_mutation(original: str, payload: str, mode: str) -> str:
    if mode == "append":
        return f"{original}\n{payload}"
    if mode == "prepend":
        return f"{payload}\n{original}"
    if mode == "replace":
        return payload
    raise ValueError(f"unknown injection mode: {mode}")


def apply_injection(body: dict, target: str, mode: str, payload: str) -> bool:
    """Mutates `body["messages"]` in place. Returns True if a matching
    message existed and was mutated.
    """
    role = TARGET_TO_ROLE.get(target)
    if role is None:
        return False
    messages = body.get("messages", [])
    message = _find_last_message(messages, role)
    if message is None:
        return False
    content = message.get("content")
    if isinstance(content, str):
        message["content"] = apply_text_mutation(content, payload, mode)
        return True
    if isinstance(content, list):
        # content-block form: mutate/append a text block
        text_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "text"]
        if text_blocks:
            block = text_blocks[-1]
            block["text"] = apply_text_mutation(block.get("text", ""), payload, mode)
        else:
            content.append({"type": "text", "text": payload})
        return True
    return False
