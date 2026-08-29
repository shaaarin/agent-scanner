"""Re-groups a Campaign's captured request TrafficEvents into distinct
conversation threads -- generator's own copy of
control-api/app/conversation_threads.py's reconstruction (same algorithm,
kept local since generator and control-api don't share a Python package;
see that module's docstring for why this grouping exists). Used by
backbone.py to pick which thread a FuzzRun/TreeRun replays against.
"""

import json


def _messages_of(event: dict) -> list[dict]:
    try:
        body = json.loads(event["raw_excerpt"])
    except (json.JSONDecodeError, TypeError):
        return []
    messages = body.get("messages")
    return messages if isinstance(messages, list) else []


def _extends_thread(shorter: list[dict], longer: list[dict]) -> bool:
    if len(shorter) > len(longer):
        return False
    return all(a == b for a, b in zip(shorter, longer))


def reconstruct_threads(request_events: list[dict]) -> list[dict]:
    """`request_events`: direction="request" TrafficEvents for one campaign,
    any order. Returns threads in first-seen order, each:
    {"events": [...ordered TrafficEvents...], "messages": [...latest snapshot...], "last_created_at": ...}
    """
    threads: list[dict] = []
    for event in sorted(request_events, key=lambda e: e["created_at"]):
        messages = _messages_of(event)
        match = next((t for t in threads if _extends_thread(t["messages"], messages)), None)
        if match:
            match["messages"] = messages
            match["events"].append(event)
            match["last_created_at"] = event["created_at"]
        else:
            threads.append({"events": [event], "messages": messages, "last_created_at": event["created_at"]})
    return threads


def select_thread_events(request_events: list[dict], anchor_event_id: int | None) -> list[dict]:
    """Picks one thread's ordered request events: the thread whose latest
    event id matches `anchor_event_id` if given (a user's explicit pick via
    Campaign.backbone_anchor_event_id), else whichever thread most recently
    posted a new message (the default "always the latest dialogue").
    """
    threads = reconstruct_threads(request_events)
    if not threads:
        return []
    if anchor_event_id is not None:
        match = next((t for t in threads if t["events"][-1]["id"] == anchor_event_id), None)
        if match:
            return match["events"]
    return max(threads, key=lambda t: t["last_created_at"])["events"]
