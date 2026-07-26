import os

import httpx

INTERACTOR_URL = os.environ.get("INTERACTOR_URL", "http://interactor:8000")

_client = httpx.AsyncClient(base_url=INTERACTOR_URL, timeout=120.0)


async def session_turn(
    campaign_id: int, session_token: str | None, message: str | None, transcript: list[dict] | None = None
) -> dict:
    """Calls interactor's resumable /session/turn primitive -- used by
    generator/app/backbone.py to drive the single honest baseline exchange a
    Campaign's fuzzing (both direct and indirect) is built on. `message=None`
    lets interactor's own persona LLM decide the line.
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
