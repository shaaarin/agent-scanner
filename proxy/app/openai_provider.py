"""Streaming/parsing helpers for the OpenAI /v1/chat/completions format.

proxy is capture-only now (see addon.py) -- the injection/detection helpers
that used to live here moved to generator/app/injection_apply.py,
success_detector.py, response_helpers.py, since fuzzing attempts are direct
LLM calls generator makes itself, not live traffic proxy intercepts. Only
the streaming-reconstruction helpers, still needed to log a complete body
for streamed backbone responses, stay here.
"""
import json
from typing import Any


def is_streaming_request(body: dict) -> bool:
    return bool(body.get("stream"))


class StreamAccumulator:
    """Reassembles OpenAI SSE chat-completion chunks into a final message
    shape, purely so the complete body can be logged as a TrafficEvent.
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
