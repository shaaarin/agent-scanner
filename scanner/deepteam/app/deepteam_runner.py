"""Wraps `deepteam.red_team` for one scan: maps the UI's vulnerability/attack
checklist names onto DeepTeam classes, streams DeepTeam's own progress output
into the scan's live log, and maps the returned `RTTestCase`s into the JSON
shape `ScansDetail.tsx` renders.
"""
import contextlib
import io
import os
import re
from typing import Callable, Optional

from deepeval.models import OpenAIModel
from deepteam import red_team
from deepteam import attacks as _attacks
from deepteam import vulnerabilities as _vulnerabilities
from deepteam.attacks import single_turn as _single_turn

# UI checklist labels that differ from DeepTeam's class names.
VULNERABILITY_ALIASES = {
    "AgentIdentityTrustAbuse": "AgentIdentityAbuse",
    "InterAgentCommunicationCompromise": "InsecureInterAgentCommunication",
}

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

# opencode.ai/zen asks programmatic clients to identify as a real coding agent
# (custom User-Agent) and to carry a stable per-dialogue session header so it
# can route/cache prompts. The scanner's judge/simulator calls are one
# dialogue per scan run, so `scan.session_id` is the stable id.
CUSTOM_USER_AGENT = os.environ.get("LLM_CLIENT_USER_AGENT", "my-coding-agent/1.0")
OPENCODE_HOST = "opencode.ai"


def provider_headers(base_url: str, session_id: str) -> dict[str, str]:
    """Identification headers for provider requests: a real user agent always,
    plus opencode's session header when actually talking to opencode.ai."""
    headers = {"User-Agent": CUSTOM_USER_AGENT}
    if OPENCODE_HOST in (base_url or ""):
        headers["x-opencode-session"] = session_id
    return headers


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class _LogStream(io.TextIOBase):
    """A write-only stream that turns DeepTeam's Rich progress output into
    discrete log lines (Rich uses bare `\\r` for in-place updates)."""

    def __init__(self, on_line: Callable[[str], None]) -> None:
        self._on_line = on_line
        self._buffer = ""
        self._last = None

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:  # type: ignore[override]
        self._buffer += text
        while True:
            match = re.search(r"[\r\n]", self._buffer)
            if not match:
                break
            line, self._buffer = self._buffer[: match.start()], self._buffer[match.end():]
            self._emit(line)
        return len(text)

    def flush(self) -> None:  # type: ignore[override]
        if self._buffer:
            self._emit(self._buffer)
            self._buffer = ""

    def _emit(self, raw: str) -> None:
        line = _strip_ansi(raw).strip()
        if not line or line == self._last:
            return
        self._last = line
        self._on_line(line)


def _resolve_vulnerability(name: str):
    class_name = VULNERABILITY_ALIASES.get(name, name)
    cls = getattr(_vulnerabilities, class_name, None)
    if cls is None:
        raise ValueError(f"неизвестная уязвимость: {name}")
    return cls


def _resolve_attack(name: str):
    cls = getattr(_single_turn, name, None)
    if cls is None:
        cls = getattr(_attacks, name, None)
    if cls is None:
        raise ValueError(f"неизвестная атака: {name}")
    return cls


def run_deepteam(
    *,
    agent_config: dict,
    llm_model: dict,
    vulnerabilities: list[str],
    attacks: list[str],
    attacks_per_vulnerability_type: int,
    session_id: str,
    on_log: Callable[[str, str], None],
) -> list:
    """Runs one DeepTeam red-team pass. `on_log(level, message)` receives
    DeepTeam's own progress lines plus a few bookkeeping lines. Returns the
    raw list of `RTTestCase`."""
    purpose = agent_config.get("agent_purpose") or None
    simulator_model = OpenAIModel(
        model=llm_model["model"],
        api_key=llm_model["api_key"],
        base_url=llm_model["base_url"],
        default_headers=provider_headers(llm_model["base_url"], session_id),
    )

    vulnerability_objs = [
        _resolve_vulnerability(name)(
            simulator_model=simulator_model,
            evaluation_model=simulator_model,
            purpose=purpose,
        )
        for name in vulnerabilities
    ]
    attack_objs = [_resolve_attack(name)() for name in attacks]

    on_log("info", f"Уязвимости: {', '.join(vulnerabilities)}")
    on_log("info", f"Атаки: {', '.join(attacks)}")

    stream = _LogStream(lambda line: on_log("info", line))
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        assessment = red_team(
            model_callback=_build_callback(agent_config),
            vulnerabilities=vulnerability_objs,
            attacks=attack_objs,
            simulator_model=simulator_model,
            evaluation_model=simulator_model,
            attacks_per_vulnerability_type=attacks_per_vulnerability_type,
            ignore_errors=True,
            async_mode=False,
            target_purpose=purpose,
        )
    stream.flush()

    test_cases = list(getattr(assessment, "test_cases", []) or [])
    for case in test_cases:
        error = getattr(case, "error", None)
        if error:
            vuln = getattr(case, "vulnerability", None) or "unknown"
            attack = getattr(case, "attack_method", None) or ""
            on_log("error", f"Кейс {vuln}/{attack}: {error}")
    return test_cases


def _build_callback(agent_config: dict):
    from app.target import build_model_callback

    return build_model_callback(agent_config)


def results_to_payload(results: list) -> dict:
    """Maps DeepTeam `RTTestCase`s to the `ScanResults` shape the UI renders.

    DeepTeam's `score` is a *mitigation* score (higher = safer) and it counts
    a case as passed when `score > 0`; same rule here. Cases that errored
    (e.g. the tested agent never answered) are flagged and excluded from the
    denominator, exactly like DeepTeam does. `overall_score` is the fraction
    of valid cases the agent passed.
    """
    rows = []
    for case in results or []:
        error = getattr(case, "error", None)
        errored = bool(error)
        score = case.score if case.score is not None else 0.0
        passed = (not errored) and score > 0
        vuln = getattr(case, "vulnerability", None) or "unknown"
        vuln_type = getattr(case, "vulnerability_type", None)
        vuln_type_value = getattr(vuln_type, "value", None) or (str(vuln_type) if vuln_type else "")
        attack = getattr(case, "attack_method", None) or ""
        label = " / ".join(part for part in (vuln, vuln_type_value, attack) if part)
        rows.append(
            {
                "vulnerability": label,
                "passed": passed,
                "errored": errored,
                "error": str(error) if errored else None,
                "score": score,
                "reasoning": getattr(case, "reason", None) or error or "",
            }
        )

    valid = [row for row in rows if not row["errored"]]
    passed_count = sum(1 for row in valid if row["passed"])
    overall = (passed_count / len(valid)) if valid else 0.0
    return {"vulnerability_results": rows, "overall_score": overall}
