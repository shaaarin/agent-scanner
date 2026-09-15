"""mitmproxy addon: the actual MITM interception point. Runs inside the
`mitm-proxy` sidecar container in a tested agent's Pod (see
launcher/app/pod_manager.py), started via `mitmdump -s addon.py`.

Capture-only: this addon logs every chat/completions request+response as a
TrafficEvent. Can also operate in DeepTeam testing mode where it sends
DeepTeam-generated attacks to the tested agent and returns responses for
vulnerability assessment.

Transparent mode means there's no path prefix to read a session id from
(unlike the old explicit-`base_url` reverse-proxy design) -- the session id
is instead the `SESSION_ID` env var launcher injects into this sidecar,
one per Pod.
"""
import json
import os
import uuid

from mitmproxy import http

from app import control_client, openai_provider

SESSION_ID = os.environ.get("SESSION_ID", "")
CHAT_COMPLETIONS_SUFFIX = "/chat/completions"
DEEPTEAM_MODE = os.environ.get("DEEPTEAM_MODE", "false").lower() == "true"

# opencode.ai/zen asks programmatic clients to identify as a real coding
# agent (custom User-Agent) and to carry a stable per-dialogue session header
# so it can route/cache prompts. The tested agent's own code stays untouched;
# the identity is injected here, transparently, on its way out.
CUSTOM_USER_AGENT = os.environ.get("LLM_CLIENT_USER_AGENT", "my-coding-agent/1.0")
OPENCODE_HOST = "opencode.ai"


DEFAULT_PORTS = {"http": 80, "https": 443}


def _is_chat_completions(flow: http.HTTPFlow) -> bool:
    return flow.request.path.split("?")[0].endswith(CHAT_COMPLETIONS_SUFFIX)


def _inject_client_identity(flow: http.HTTPFlow) -> None:
    """Rewrite the tested agent's outbound LLM request headers so the
    provider sees a well-identified coding-agent client. Only headers are
    touched -- the body/prompt stays exactly what the agent sent."""
    flow.request.headers["User-Agent"] = CUSTOM_USER_AGENT
    if SESSION_ID and OPENCODE_HOST in flow.request.pretty_host:
        flow.request.headers["x-opencode-session"] = SESSION_ID


def _upstream_base_url(flow: http.HTTPFlow) -> str:
    """The real connection target mitmproxy actually intercepted (scheme +
    host + non-default port) -- not the `Host` header (`pretty_host`, used
    for the existing display-only `host` field). This is what lets
    generator's direct_llm.py call the tested agent's own real LLM directly
    later, using the agent's own real endpoint -- see
    generator/app/direct_llm.py::resolve_target_credential.
    """
    scheme = flow.request.scheme
    host = flow.request.host
    port = flow.request.port
    if port == DEFAULT_PORTS.get(scheme):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


class _StreamAccumulateCallback:
    """mitmproxy stream callback: passes SSE chunks through unmodified while
    feeding them into a StreamAccumulator so the final assembled body still
    gets logged -- streaming responses are observed, never rewritten.
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
    async def request(self, flow: http.HTTPFlow) -> None:
        if not _is_chat_completions(flow):
            return
        try:
            body = json.loads(flow.request.content or b"{}")
        except json.JSONDecodeError:
            return

        _inject_client_identity(flow)

        scan = await control_client.get_active_scan(SESSION_ID)
        flow.metadata["scan"] = scan
        flow_id = str(uuid.uuid4())
        flow.metadata["flow_id"] = flow_id

        await self._log_event(
            scan=scan,
            flow_id=flow_id,
            direction="request",
            host=flow.request.pretty_host,
            raw_excerpt=json.dumps(body),
            upstream_base_url=_upstream_base_url(flow),
            request_authorization=flow.request.headers.get("Authorization", ""),
        )

    async def responseheaders(self, flow: http.HTTPFlow) -> None:
        if not _is_chat_completions(flow):
            return
        try:
            request_body = json.loads(flow.request.content or b"{}")
        except json.JSONDecodeError:
            request_body = {}
        if openai_provider.is_streaming_request(request_body):
            flow.response.stream = _StreamAccumulateCallback()

    async def response(self, flow: http.HTTPFlow) -> None:
        if not _is_chat_completions(flow):
            return
        scan = flow.metadata.get("scan")
        flow_id = flow.metadata.get("flow_id", str(uuid.uuid4()))

        stream_cb = flow.response.stream
        if isinstance(stream_cb, _StreamAccumulateCallback):
            response_body = stream_cb.accumulator.as_response_body()
        else:
            try:
                response_body = json.loads(flow.response.content or b"{}")
            except json.JSONDecodeError:
                return

        await self._log_event(
            scan=scan,
            flow_id=flow_id,
            direction="response",
            host=flow.request.pretty_host,
            raw_excerpt=json.dumps(response_body),
        )

    async def _log_event(
        self, *, scan, flow_id, direction, host, raw_excerpt, upstream_base_url=None, request_authorization=None
    ) -> None:
        await control_client.post_event(
            {
                "session_id": SESSION_ID,
                "scan_id": scan["scan_id"] if scan else None,
                "flow_id": flow_id,
                "direction": direction,
                "provider": "openai",
                "host": host,
                "path": CHAT_COMPLETIONS_SUFFIX,
                "injected": False,
                "injection_target": None,
                "success_detected": False,
                "detail": "",
                "raw_excerpt": raw_excerpt,
                "upstream_base_url": upstream_base_url,
                "request_authorization": request_authorization,
            }
        )


addons = [InjectionAddon()]
