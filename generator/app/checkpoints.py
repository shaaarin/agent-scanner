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
    [{"occurrence_index": 1, "tool_name": ..., "tool_result": ...}, ...] --
    1-indexed, matching Campaign.inject_at_occurrence's convention.

    Known limitation: TrafficEvent.raw_excerpt is truncated to 4096 bytes
    (same truncation applied everywhere else in the platform), so a request
    body that grows past that in a long conversation may fail to parse here
    -- such events are skipped rather than raising, so checkpoint discovery
    degrades gracefully (fewer checkpoints found) rather than crashing a run.
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
                    }
                )
        prev_tool_count = len(tool_messages)

    return checkpoints
