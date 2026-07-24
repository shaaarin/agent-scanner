import os

import httpx

INTERACTOR_URL = os.environ.get("INTERACTOR_URL", "http://interactor:8000")

_client = httpx.AsyncClient(base_url=INTERACTOR_URL, timeout=120.0)


async def run_one_shot(campaign_id: int) -> dict:
    """Delivers exactly one exchange via interactor's existing /run, unchanged
    -- this is enough to let proxy inject into that exchange's user_message or
    tool_result exactly as it already does for a normal campaign.
    """
    resp = await _client.post("/run", json={"campaign_id": campaign_id, "max_turns": 1})
    resp.raise_for_status()
    return resp.json()


async def session_turn(
    campaign_id: int, session_token: str | None, message: str | None, transcript: list[dict] | None = None
) -> dict:
    """Calls interactor's resumable /session/turn primitive -- used by
    generator/app/tree_engine.py to drive a conversation turn-by-turn
    (backbone or a probe's replay), rather than /run's all-turns-in-one-call
    loop. `message=None` lets interactor's own persona LLM decide the next
    line, given `transcript` (this caller's own running record of the
    conversation so far).
    """
    resp = await _client.post(
        "/session/turn",
        json={
            "campaign_id": campaign_id,
            "session_token": session_token,
            "message": message,
            "transcript": transcript or [],
        },
    )
    resp.raise_for_status()
    return resp.json()
