"""Parsing/injection helpers for the OpenAI /v1/chat/completions format."""
import json
from typing import Any, Optional


def _find_last_message(messages: list[dict], role: str) -> Optional[dict]:
    for message in reversed(messages):
        if message.get("role") == role:
            return message
    return None


TARGET_TO_ROLE = {
    "user_message": "user",
    "tool_result": "tool",
    "system_prompt": "system",
}


def apply_text_mutation(original: str, payload: str, mode: str) -> str:
    if mode == "append":
        return f"{original}\n{payload}"
    if mode == "prepend":
        return f"{payload}\n{original}"
    if mode == "replace":
        return payload
    raise ValueError(f"unknown injection mode: {mode}")


def has_matching_message(body: dict, target: str) -> bool:
    """Whether `body` is eligible for a request-side injection at `target`,
    without mutating anything -- used to count occurrences for
    Campaign.inject_at_occurrence before deciding whether to actually inject.
    """
    role = TARGET_TO_ROLE.get(target)
    if role is None:
        return False
    return _find_last_message(body.get("messages", []), role) is not None


def inject_request(body: dict, target: str, mode: str, payload: str) -> bool:
    """Mutates `body` in place for a request-side injection target.

    Returns True if an injection was actually applied (a matching message existed).
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


def _parse_tool_call_payload(payload: str) -> Optional[dict]:
    try:
        parsed = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(parsed, dict) and "name" in parsed:
        return parsed
    return None


def inject_response(body: dict, mode: str, payload: str) -> bool:
    """Mutates a non-streamed chat-completion response body for the
    assistant_response injection target.

    If `payload` parses as a JSON object with a "name" key, it is treated as a
    fabricated tool call and spliced into message.tool_calls. Otherwise it is
    treated as plain text and applied to message.content.
    """
    choices = body.get("choices") or []
    if not choices:
        return False
    message = choices[0].setdefault("message", {})

    tool_call_spec = _parse_tool_call_payload(payload)
    if tool_call_spec is not None:
        tool_calls = message.setdefault("tool_calls", [])
        fabricated = {
            "id": f"call_injected_{len(tool_calls)}",
            "type": "function",
            "function": {
                "name": tool_call_spec.get("name", ""),
                "arguments": json.dumps(tool_call_spec.get("arguments", {})),
            },
        }
        if mode == "replace":
            message["tool_calls"] = [fabricated]
        else:
            tool_calls.append(fabricated)
        choices[0]["finish_reason"] = "tool_calls"
        return True

    content = message.get("content") or ""
    message["content"] = apply_text_mutation(content, payload, mode)
    return True


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


def is_streaming_request(body: dict) -> bool:
    return bool(body.get("stream"))


class StreamAccumulator:
    """Reassembles OpenAI SSE chat-completion chunks into a final message
    shape compatible with iter_tool_calls/get_response_text, for detection
    purposes only. Does not support rewriting the stream in this MVP.
    """

    def __init__(self) -> None:
        self._content_parts: list[str] = []
        self._tool_calls: dict[int, dict] = {}

    def feed_chunk(self, chunk: dict) -> None:
        choices = chunk.get("choices") or []
        if not choices:
            return
        delta = choices[0].get("delta", {})
        if "content" in delta and delta["content"]:
            self._content_parts.append(delta["content"])
        for tc_delta in delta.get("tool_calls") or []:
            idx = tc_delta.get("index", 0)
            entry = self._tool_calls.setdefault(
                idx, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
            )
            if tc_delta.get("id"):
                entry["id"] = tc_delta["id"]
            function_delta = tc_delta.get("function") or {}
            if function_delta.get("name"):
                entry["function"]["name"] += function_delta["name"]
            if function_delta.get("arguments"):
                entry["function"]["arguments"] += function_delta["arguments"]

    def as_response_body(self) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": "".join(self._content_parts)}
        if self._tool_calls:
            message["tool_calls"] = [self._tool_calls[i] for i in sorted(self._tool_calls)]
        return {"choices": [{"message": message}]}


def parse_sse_lines(raw_chunk: bytes, buffer: str) -> tuple[list[dict], str]:
    """Splits a raw SSE byte chunk (appended to `buffer`) into complete
    `data: {...}` JSON events, returning (events, remaining_buffer)."""
    buffer += raw_chunk.decode("utf-8", errors="ignore")
    events: list[dict] = []
    while "\n\n" in buffer:
        frame, buffer = buffer.split("\n\n", 1)
        for line in frame.splitlines():
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                continue
            try:
                events.append(json.loads(data))
            except json.JSONDecodeError:
                continue
    return events, buffer
