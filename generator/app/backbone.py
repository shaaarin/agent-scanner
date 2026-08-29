"""The one honest baseline exchange a Campaign's fuzzing is built on.

Drives the real tested agent (via `interactor`, which `proxy` transparently
intercepts) exactly once per Campaign, capturing every internal LLM exchange
as TrafficEvents. Both `fuzz_engine.py` (direct/user_message) and
`tree_engine.py` (indirect/tool_result) call `ensure_backbone` before their
attempt loops and replay directly against the captured request bodies from
then on -- no agent call, no proxy, and critically no new Campaign row is
ever created for an individual attempt.

`ensure_backbone` is idempotent (checks for existing captured events first)
so whichever of the two engines starts first does the one honest run and the
other one just reuses it. The asyncio.Lock registry below only serializes
that check-then-drive race within a single generator process -- acceptable
for this MVP (single generator instance in local/dev deployment), not a
distributed lock.

More than one interactor run can share a Campaign's session_id (re-running
"Запустить диалог", or two runs overlapping in time), so more than one
distinct conversation can exist under one Campaign -- `ensure_backbone`
picks exactly one thread's events to return (see conversation_threads.py),
defaulting to whichever thread most recently posted a new message, unless
`Campaign.backbone_anchor_event_id` pins a specific one.
"""
import asyncio

from app import control_client, interactor_client
from app.conversation_threads import select_thread_events

EVENTS_LIMIT = 1000

_locks: dict[int, asyncio.Lock] = {}


def _lock_for(base_campaign_id: int) -> asyncio.Lock:
    lock = _locks.get(base_campaign_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[base_campaign_id] = lock
    return lock


async def _captured_requests(base_campaign_id: int) -> list[dict]:
    events = await control_client.list_campaign_events(base_campaign_id, limit=EVENTS_LIMIT)
    requests = [e for e in events if e["direction"] == "request"]
    return sorted(requests, key=lambda e: e["created_at"])


async def ensure_backbone(base_campaign: dict) -> list[dict]:
    """Returns one conversation thread's captured request-direction
    TrafficEvents (see conversation_threads.py), driving the one honest
    exchange via interactor if none exist yet.
    """
    base_campaign_id = base_campaign["id"]
    anchor_event_id = base_campaign.get("backbone_anchor_event_id")
    async with _lock_for(base_campaign_id):
        requests = await _captured_requests(base_campaign_id)
        if requests:
            return select_thread_events(requests, anchor_event_id)

        await interactor_client.session_turn(base_campaign_id, session_token=None, message=None)
        requests = await _captured_requests(base_campaign_id)
        return select_thread_events(requests, anchor_event_id)
