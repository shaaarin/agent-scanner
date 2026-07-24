"""Provider-agnostic injection entry points. Only the OpenAI format is wired
up in this MVP; a future provider just needs to implement the same functions
as openai_provider.py and get dispatched on here.
"""
from app import openai_provider

REQUEST_TARGETS = {"user_message", "tool_result", "system_prompt"}
RESPONSE_TARGETS = {"assistant_response"}


def is_eligible_for_request_injection(body: dict, target: str) -> bool:
    """Whether `body` has a matching-role message for `target`, without
    mutating anything -- used to count occurrences for
    Campaign.inject_at_occurrence.
    """
    if target not in REQUEST_TARGETS:
        return False
    return openai_provider.has_matching_message(body, target)


def inject_into_request(body: dict, target: str, mode: str, payload: str) -> bool:
    if target not in REQUEST_TARGETS:
        return False
    return openai_provider.inject_request(body, target, mode, payload)


def inject_into_response(body: dict, target: str, mode: str, payload: str) -> bool:
    if target not in RESPONSE_TARGETS:
        return False
    return openai_provider.inject_response(body, mode, payload)
