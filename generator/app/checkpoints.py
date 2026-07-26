"""Checkpoint discovery for the injection tree: reads control-api's own
TrafficEvent log for a campaign to find every point the agent received a new
tool result, regardless of how many *external* interactor turns it took to
produce them -- proxy intercepts every internal LLM-bound exchange the agent
makes, independent of interaction_mode (api or langgraph). See
docs/architecture.md's "Injection tree" section.
"""

import json


def checkpoints_from_events(events: list[dict]) -> list[dict]:
    """`events`: TrafficEvents for one campaign, any order (re-sorted here by
    created_at). Returns checkpoints in chronological order:
    [{"occurrence_index": 1, "tool_name": ..., "tool_result": ..., "request_body": {...}, "flow_id": ...}, ...]
    -- 1-indexed. `request_body` is the exact captured messages array (plus
    tools/model/etc.) as of the request where that tool result first
    appeared as the newest one -- this is what tree_engine.py mutates and
    replays directly to the tested LLM (see generator/app/direct_llm.py),
    so it must be the full, untruncated body. `flow_id` matches this same
    request's paired response TrafficEvent, letting tree_engine look up what
    the real (clean) backbone actually decided to do right after seeing
    this tool result, for the divergence comparison.
    """
    request_events = sorted(
        (e for e in events if e["direction"] == "request"),
        key=lambda e: e["created_at"],
    )

    checkpoints: list[dict] = []
    prev_tool_count = 0
    for event in request_events:
        try:
            body = json.loads(event["raw_excerpt"])
        except (json.JSONDecodeError, TypeError):
            continue

        messages = body.get("messages", [])
        tool_call_names = {}
        for message in messages:
            if message.get("role") == "assistant":
                for tool_call in message.get("tool_calls") or []:
                    tool_call_names[tool_call.get("id")] = tool_call.get("function", {}).get("name", "")

        tool_messages = [m for m in messages if m.get("role") == "tool"]
        if len(tool_messages) > prev_tool_count:
            for message in tool_messages[prev_tool_count:]:
                content = message.get("content", "")
                if not isinstance(content, str):
                    content = json.dumps(content)
                checkpoints.append(
                    {
                        "occurrence_index": len(checkpoints) + 1,
                        "tool_name": tool_call_names.get(message.get("tool_call_id"), ""),
                        "tool_result": content,
                        "request_body": body,
                        "flow_id": event["flow_id"],
                    }
                )
        prev_tool_count = len(tool_messages)

    return checkpoints
