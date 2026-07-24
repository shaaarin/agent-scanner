import json

import litellm


class GenerationError(Exception):
    pass


def _litellm_model(credential: dict) -> str:
    provider = credential.get("provider_type", "openai")
    return f"{provider}/{credential['model']}"


def _api_base(credential: dict) -> str | None:
    """litellm's OpenAI-compatible provider expects api_base to end in
    "/v1" (it appends "/chat/completions" itself, matching the OpenAI SDK
    convention); litellm's Anthropic provider expects the bare host instead.
    LLMModel.base_url is stored without a "/v1" suffix, so only the openai
    path needs the suffix appended here.
    """
    base_url = credential.get("base_url")
    if not base_url:
        return None
    base_url = base_url.rstrip("/")
    if credential.get("provider_type", "openai") == "openai" and not base_url.endswith("/v1"):
        return f"{base_url}/v1"
    return base_url


async def call_chat_completion(credential: dict, system_prompt: str, user_prompt: str) -> str:
    """Calls the configured LLM via LiteLLM's unified interface -- works for
    any provider LiteLLM supports (OpenAI, Anthropic, ...) by picking the
    right model prefix from the LLMModel's provider_type, and
    passing base_url through as a custom api_base (which also makes this
    work against our OpenAI-wire-compatible mock servers). Never goes
    through `proxy` -- the generator's own LLM calls are not themselves the
    system under test.
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


def strip_json_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return text


def parse_template_json(raw: str) -> dict:
    text = strip_json_fences(raw)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GenerationError(f"LLM did not return valid JSON: {exc}\nraw: {raw}") from exc

    required = {"name", "description", "target", "mode", "payload", "success_indicator", "success_indicator_field", "tags"}
    missing = required - parsed.keys()
    if missing:
        raise GenerationError(f"LLM response missing required fields: {missing}")
    return parsed
