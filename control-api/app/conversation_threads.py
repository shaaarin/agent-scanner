"""Re-groups a Campaign's captured request TrafficEvents into distinct
conversation threads. More than one interactor run can share a session_id
(re-running "Запустить диалог", or two runs overlapping in time), so the raw
request-event stream can interleave two or more unrelated, independently
growing conversations -- picking "most recent event" without this grouping
flips between them and looks like turns randomly vanish (see
web/src/components/ConversationView.tsx, which does the same reconstruction
client-side for the live view; this is the server-side twin used to let a
user pin fuzzing/tree runs to one specific thread via
Campaign.backbone_anchor_event_id, see generator/app/backbone.py).
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


def latest_thread(threads: list[dict]) -> dict | None:
    if not threads:
        return None
    return max(threads, key=lambda t: t["last_created_at"])
