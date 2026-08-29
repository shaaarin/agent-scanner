"""Calls the tested agent's own real LLM directly with a captured (and
mutated) messages array -- the actual fuzzing-attempt delivery mechanism.

No ephemeral Campaign, no `interactor`, no `proxy` for the attempt itself:
every fuzz/tree attempt is a single direct chat-completion call against the
agent's own real credentials -- but those credentials are never configured
anywhere. `proxy` observes them directly during the one honest baseline
exchange (the real upstream connection + the real `Authorization` header
the agent's own LLM client sent, see proxy/addon.py) and logs them on the
captured `TrafficEvent`; `resolve_target_credential` below just reads them
back off that event. Never the platform's own `LLMModel` rows, which stay
reserved for interactor/generator/judge roles -- see
control-api/app/models.py's `LLMModel` docstring.
"""

import litellm

from app import llm_client


class DirectLLMError(Exception):
    pass


def resolve_target_credential(request_event: dict) -> dict:
    """`request_event` is a captured request-direction `TrafficEvent` from
    the honest baseline exchange (e.g. `backbone_requests[0]`) -- base
    URL/auth are constant for the whole exchange, so any one of them works.
    """
    base_url = request_event.get("upstream_base_url")
    if not base_url:
        raise DirectLLMError(
            "captured backbone request has no upstream_base_url -- cannot resolve "
            "the tested agent's own LLM credentials"
        )
    auth = request_event.get("request_authorization") or ""
    api_key = auth[7:] if auth.lower().startswith("bearer ") else auth
    # Deliberately not fatal if empty: some self-hosted OpenAI-compatible
    # servers take no auth at all. If the real endpoint does need a key and
    # none was captured, the direct call below will fail with that
    # endpoint's own 401 -- a legitimate attempt failure, not something to
    # preemptively block.
    return {
        "base_url": base_url,
        "api_key": api_key or "not-required",
        "provider_type": "openai",
    }


async def call_raw_completion(credential: dict, body: dict) -> dict:
    """`body` is a full captured (and mutated) OpenAI chat-completions
    request body -- forwarded as-is (messages, tools, tool_choice,
    temperature, ...) except `model`/`stream`, which are handled explicitly:
    the model name comes from the captured body itself (the exact model the
    real agent's LLM client requested), and streaming is always forced off
    so the result is a plain dict usable by success_detector/response_helpers.
    """
    if "model" not in body:
        raise DirectLLMError('captured request body has no "model" field to replay')
    # `stream_options` is only meaningful together with stream:true -- many
    # OpenAI-compatible backends reject a non-streaming request that still
    # carries it, which would fail every attempt for a streaming agent.
    payload = {
        k: v for k, v in body.items() if k not in ("model", "stream", "stream_options")
    }
    response = await litellm.acompletion(
        model=f"{credential['provider_type']}/{body['model']}",
        api_key=credential["api_key"],
        api_base=llm_client._api_base(credential),
        **payload,
    )
    return response.model_dump()
