import re

import litellm


def _litellm_model(credential: dict) -> str:
    provider = credential.get("provider_type", "openai")
    return f"{provider}/{credential['model']}"


def _api_base(credential: dict) -> str | None:
    """See generator/app/llm_client.py's identical helper for the reasoning:
    litellm's OpenAI-compatible provider wants api_base to end in a version
    segment, its Anthropic provider wants the bare host.
    """
    base_url = credential.get("base_url")
    if not base_url:
        return None
    base_url = base_url.rstrip("/")
    # Any trailing version segment counts (/v1 for OpenAI-style, /v4 for
    # z.ai, ...) -- appending /v1 to an already-versioned URL produces
    # /v4/v1/chat/completions, a guaranteed 404.
    if credential.get("provider_type", "openai") == "openai" and not re.search(
        r"/v\d+$", base_url
    ):
        return f"{base_url}/v1"
    return base_url


async def call_chat_completion(
    credential: dict, system_prompt: str, user_prompt: str
) -> str:
    """Calls the configured LLM via LiteLLM's unified interface -- works for
    any provider LiteLLM supports, picked via the LLMModel's
    provider_type -- never through the agent-scanner proxy, since the
    interactor's own LLM calls are not themselves the system under test.
    """
    response = await litellm.acompletion(
        model=_litellm_model(credential),
        api_key=credential["api_key"],
        api_base=_api_base(credential),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content
