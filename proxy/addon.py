"""mitmproxy addon: the actual MITM interception point. Runs inside the
`mitm-proxy` sidecar container in a tested agent's Pod (see
launcher/app/pod_manager.py), started via `mitmdump -s addon.py`.

Transparent mode means there's no path prefix to read a session id from
(unlike the old explicit-`base_url` reverse-proxy design) -- the session id
is instead the `SESSION_ID` env var launcher injects into this sidecar,
one per Pod. All the actual body transformation/detection logic
(openai_provider/injector/detector/vuln_signatures) is untouched from the
prior reverse-proxy design; only the transport layer changed.
"""
import json
import os
import random
import uuid

from mitmproxy import http

from app import control_client, detector, injector, openai_provider

SESSION_ID = os.environ.get("SESSION_ID", "")
CHAT_COMPLETIONS_SUFFIX = "/chat/completions"
RAW_EXCERPT_LIMIT = 4096


def _truncate(text: str) -> str:
    return text[:RAW_EXCERPT_LIMIT]


def _is_chat_completions(flow: http.HTTPFlow) -> bool:
    return flow.request.path.split("?")[0].endswith(CHAT_COMPLETIONS_SUFFIX)


class _StreamAccumulateCallback:
    """mitmproxy stream callback: passes SSE chunks through unmodified while
    feeding them into a StreamAccumulator for detection -- streaming
    responses are observed, never rewritten, same limitation as before.
    """

    def __init__(self) -> None:
        self.accumulator = openai_provider.StreamAccumulator()
        self._buffer = ""

    def __call__(self, chunk: bytes) -> bytes:
        events, self._buffer = openai_provider.parse_sse_lines(chunk, self._buffer)
        for event in events:
            self.accumulator.feed_chunk(event)
        return chunk


class InjectionAddon:
    def __init__(self) -> None:
        # (session_id, campaign_id) -> count of target-eligible exchanges seen
        # so far, for Campaign.inject_at_occurrence. Reset implicitly whenever
        # a different campaign_id becomes active (a fresh ephemeral campaign
        # per fuzz attempt always starts this counter at 0).
        self._occurrence_counters: dict[tuple[str, int], int] = {}

    def _should_inject(self, campaign: dict, template: dict, body: dict) -> bool:
        target_occurrence = campaign.get("inject_at_occurrence")
        if target_occurrence is None:
            return random.random() < campaign["injection_rate"]

        if not injector.is_eligible_for_request_injection(body, template["target"]):
            return False
        key = (SESSION_ID, campaign["campaign_id"])
        occurrence = self._occurrence_counters.get(key, 0) + 1
        self._occurrence_counters[key] = occurrence
        return occurrence == target_occurrence

    async def request(self, flow: http.HTTPFlow) -> None:
        if not _is_chat_completions(flow):
            return
        try:
            body = json.loads(flow.request.content or b"{}")
        except json.JSONDecodeError:
            return

        campaign = await control_client.get_active_campaign(SESSION_ID)
        flow.metadata["campaign"] = campaign
        flow.metadata["request_body"] = body
        flow_id = str(uuid.uuid4())
        flow.metadata["flow_id"] = flow_id

        injected_request = False
        injection_target = None
        if campaign is not None and self._should_inject(campaign, campaign["template"], body):
            template = campaign["template"]
            if injector.inject_into_request(body, template["target"], template["mode"], template["payload"]):
                injected_request = True
                injection_target = template["target"]
                flow.request.content = json.dumps(body).encode()

        await self._log_event(
            campaign=campaign,
            flow_id=flow_id,
            direction="request",
            host=flow.request.pretty_host,
            injected=injected_request,
            injection_target=injection_target,
            success_detected=False,
            detail="",
            raw_excerpt=json.dumps(body),
        )

    async def responseheaders(self, flow: http.HTTPFlow) -> None:
        if not _is_chat_completions(flow):
            return
        request_body = flow.metadata.get("request_body") or {}
        if openai_provider.is_streaming_request(request_body):
            flow.response.stream = _StreamAccumulateCallback()

    async def response(self, flow: http.HTTPFlow) -> None:
        if not _is_chat_completions(flow):
            return
        campaign = flow.metadata.get("campaign")
        flow_id = flow.metadata.get("flow_id", str(uuid.uuid4()))
        request_body = flow.metadata.get("request_body") or {}

        stream_cb = flow.response.stream
        injected_response = False
        injection_target = None

        if isinstance(stream_cb, _StreamAccumulateCallback):
            response_body = stream_cb.accumulator.as_response_body()
        else:
            try:
                response_body = json.loads(flow.response.content or b"{}")
            except json.JSONDecodeError:
                return

            if campaign is not None and campaign["template"]["target"] == "assistant_response":
                template = campaign["template"]
                if injector.inject_into_response(response_body, template["target"], template["mode"], template["payload"]):
                    injected_response = True
                    injection_target = template["target"]
                    flow.response.content = json.dumps(response_body).encode()

        success_detected = False
        detail = ""
        if campaign is not None:
            success_detected, detail = detector.evaluate(
                request_body,
                response_body,
                campaign["template"]["success_indicator"],
                campaign["template"]["success_indicator_field"],
            )

        await self._log_event(
            campaign=campaign,
            flow_id=flow_id,
            direction="response",
            host=flow.request.pretty_host,
            injected=injected_response,
            injection_target=injection_target,
            success_detected=success_detected,
            detail=detail,
            raw_excerpt=json.dumps(response_body),
        )

    async def _log_event(
        self, *, campaign, flow_id, direction, host, injected, injection_target, success_detected, detail, raw_excerpt
    ) -> None:
        await control_client.post_event(
            {
                "session_id": SESSION_ID,
                "campaign_id": campaign["campaign_id"] if campaign else None,
                "flow_id": flow_id,
                "direction": direction,
                "provider": "openai",
                "host": host,
                "path": CHAT_COMPLETIONS_SUFFIX,
                "injected": injected,
                "injection_target": injection_target,
                "success_detected": success_detected,
                "detail": detail,
                "raw_excerpt": _truncate(raw_excerpt),
            }
        )


addons = [InjectionAddon()]
