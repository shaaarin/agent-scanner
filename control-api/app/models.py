from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InjectionTarget(str, Enum):
    USER_MESSAGE = "user_message"
    TOOL_RESULT = "tool_result"
    ASSISTANT_RESPONSE = "assistant_response"
    SYSTEM_PROMPT = "system_prompt"


class InjectionMode(str, Enum):
    APPEND = "append"
    PREPEND = "prepend"
    REPLACE = "replace"


class SuccessIndicatorField(str, Enum):
    TOOL_NAME = "tool_name"
    TOOL_ARGUMENTS = "tool_arguments"
    RESPONSE_TEXT = "response_text"


class InjectionTemplate(SQLModel, table=True):
    """A single prompt-injection payload that can be dropped into LLM traffic."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str = ""
    target: InjectionTarget
    mode: InjectionMode = InjectionMode.APPEND
    payload: str
    success_indicator: Optional[str] = None  # regex
    success_indicator_field: SuccessIndicatorField = SuccessIndicatorField.TOOL_NAME
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class CampaignStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"


class ProviderType(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class LLMModel(SQLModel, table=True):
    """A real LLM client entered via the web UI: a provider + model + base
    URL + API key. Used by `interactor`/`generator` (`Campaign.interactor_llm_model_id`,
    `Campaign.generator_llm_model_id`) for the platform's own outbound LLM
    calls, via LiteLLM (see their `llm_client.py`), so any provider LiteLLM
    supports works. There is deliberately no "target" role here: the tested
    agent's own LLM traffic is intercepted transparently via MITM (see
    `launcher/app/pod_manager.py`, `proxy/addon.py`) using whatever real
    provider config the agent itself is given via `AgentConfig.env_vars` --
    the platform never needs to know or resolve that upstream itself.

    Stored in plain text for this MVP: not encrypted at rest. This is a
    known, deliberately accepted tech-debt item -- see docs/architecture.md.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    provider_type: ProviderType = ProviderType.OPENAI
    base_url: str
    api_key: str
    model: str = "gpt-4o-mini"  # passed to litellm, e.g. "gpt-4o-mini" or "claude-3-5-sonnet-latest"
    created_at: datetime = Field(default_factory=utcnow)


class InteractionMode(str, Enum):
    NONE = "none"
    API = "api"
    LANGGRAPH = "langgraph"


class AgentConfig(SQLModel, table=True):
    """How to build and launch a tested agent in Kubernetes, and if needed,
    how to hold a conversation with it (its external API surface --
    distinct from the agent's own internal LLM traffic, which always flows
    through the proxy regardless of this config).

    The agent's source is fetched from a git repository and built in-cluster
    (git-clone + Kaniko, see the `launcher` service) rather than referencing
    a pre-built image. Launch flow: clone repo -> read env_example_path (if
    set) to auto-fill env_vars with the repo's own declared defaults -> build
    dockerfile_path -> run the resulting image with env_vars, exposing
    api_port (if set) via an auto-created NodePort Service -- see
    docs/architecture.md.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    git_repo_url: str
    git_ref: str = "main"
    git_access_token: Optional[str] = None  # PAT for private HTTPS repos -- see launcher/app/git_auth.py. Plain text, same accepted MVP tech debt as LLMModel.api_key.
    dockerfile_path: str = "Dockerfile"  # path to the Dockerfile, relative to the repo root (build context is always the repo root)
    env_example_path: Optional[str] = None  # e.g. ".env.example" -- launcher reads this to auto-fill env_vars with the repo's own declared defaults
    api_port: Optional[int] = None  # container port the agent listens on, if any -- launcher exposes it via an auto-created NodePort Service
    entrypoint: Optional[list[str]] = Field(default=None, sa_column=Column(JSON))
    env_vars: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    resources: Optional[dict] = Field(default=None, sa_column=Column(JSON))  # e.g. {"cpu": "500m", "memory": "512Mi"}
    agent_purpose: Optional[str] = None  # what this agent is for -- context for the interactor's legit-user persona
    interaction_mode: InteractionMode = InteractionMode.NONE
    # api_config (interaction_mode=api): {"url", "method", "request_body_template"
    #   (arbitrary JSON with a "{{message}}" placeholder), "response_field"
    #   (dot-path into the JSON response, e.g. "reply" or "data.0.text"),
    #   "headers" (optional dict)}.
    api_config: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    # langgraph_config (interaction_mode=langgraph): {"base_url", "assistant_id",
    #   "api_key" (optional, sent as X-Api-Key for LangGraph Platform deployments)}.
    langgraph_config: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class InteractorPersona(str, Enum):
    """Only BENIGN_USER is honored by `interactor` in this iteration -- a
    legitimate user who was given an instruction (what they're allowed to
    do) and the agent's purpose, both via the web UI. ATTACKER is kept in
    the schema for a future iteration but is not currently implemented.
    """

    ATTACKER = "attacker"
    BENIGN_USER = "benign_user"


class Campaign(SQLModel, table=True):
    """Binds an injection template to a specific agent/session being tested."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    session_id: str = Field(index=True)
    template_id: int = Field(foreign_key="injectiontemplate.id")
    status: CampaignStatus = CampaignStatus.PAUSED
    injection_rate: float = 1.0
    inject_at_occurrence: Optional[int] = None  # 1-indexed; if set, proxy injects only on this Nth target-eligible exchange for this campaign, ignoring injection_rate -- see tree_engine.py
    agent_config_id: Optional[int] = Field(default=None, foreign_key="agentconfig.id")
    interactor_llm_model_id: Optional[int] = Field(default=None, foreign_key="llmmodel.id")
    generator_llm_model_id: Optional[int] = Field(default=None, foreign_key="llmmodel.id")
    interactor_persona: Optional[InteractorPersona] = None
    user_instruction: Optional[str] = None  # what the interactor's legit-user persona is allowed/told to do
    agent_namespace: Optional[str] = None
    agent_pod_name: Optional[str] = None
    build_job_name: Optional[str] = None
    built_image: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class EventDirection(str, Enum):
    REQUEST = "request"
    RESPONSE = "response"


class TrafficEvent(SQLModel, table=True):
    """Every intercepted request/response the proxy reports back."""

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    campaign_id: Optional[int] = Field(default=None, foreign_key="campaign.id")
    flow_id: str = Field(index=True)
    direction: EventDirection
    provider: str = "openai"
    host: str = ""
    path: str = ""
    injected: bool = False
    injection_target: Optional[str] = None
    success_detected: bool = False
    detail: str = ""
    raw_excerpt: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class FuzzMode(str, Enum):
    """ADAPTIVE reuses this run's own failed attempts as feedback for the next
    mutation (the same reasoning as generator's existing `/adapt`); NON_ADAPTIVE
    is a pure mutation search with no failure-reasoning fed back (closer to
    GPTFuzzer's mutate-and-test loop).
    """

    ADAPTIVE = "adaptive"
    NON_ADAPTIVE = "non_adaptive"


class FuzzRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"


class FuzzRun(SQLModel, table=True):
    """A budget-driven fuzzing search over InjectionTemplate variants against
    one already-configured Campaign (`base_campaign_id` supplies session_id/
    agent_config_id/interactor_llm_model_id/generator_llm_model_id -- the fuzz
    loop clones a fresh ephemeral Campaign per iteration rather than mutating
    the base one, see FuzzAttempt.campaign_id).
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    base_campaign_id: int = Field(foreign_key="campaign.id")
    injection_target: InjectionTarget
    mode: FuzzMode = FuzzMode.NON_ADAPTIVE
    seed_template_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    judge_llm_model_id: Optional[int] = Field(default=None, foreign_key="llmmodel.id")
    max_iterations: int = 20
    stop_on_success: bool = True
    status: FuzzRunStatus = FuzzRunStatus.PENDING
    success_attempt_id: Optional[int] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class FuzzAttempt(SQLModel, table=True):
    """One iteration of a FuzzRun's search: which seed (bandit arm) was
    picked, the mutated template actually delivered, the ephemeral Campaign
    used to deliver it, and the combined detector+judge verdict.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    fuzz_run_id: int = Field(foreign_key="fuzzrun.id", index=True)
    iteration: int
    seed_template_id: int = Field(foreign_key="injectiontemplate.id")
    template_id: int = Field(foreign_key="injectiontemplate.id")
    campaign_id: int = Field(foreign_key="campaign.id")
    mutation_strategy: str = ""
    detector_success: bool = False
    judge_score: float = 0.0
    judge_verdict: str = ""
    reward: float = 0.0
    success: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class TreeRun(SQLModel, table=True):
    """A budget-driven per-tool-call A/B fuzzing run: walks one real, clean
    conversation (the backbone, via `base_campaign_id`) forward, then fuzzes
    each tool-result checkpoint the backbone actually produced -- see
    docs/architecture.md's "Injection tree" section. `base_campaign_id` must
    have `injection_rate=0.0`/`inject_at_occurrence=None` (a genuinely clean
    backbone); works for either `interaction_mode` (`api` or `langgraph`).
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    base_campaign_id: int = Field(foreign_key="campaign.id")
    seed_template_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    judge_llm_model_id: Optional[int] = Field(default=None, foreign_key="llmmodel.id")
    max_backbone_turns: int = 10
    max_probe_turns: int = 10
    max_checkpoints: Optional[int] = None
    attempts_per_checkpoint: int = 5
    mode: FuzzMode = FuzzMode.NON_ADAPTIVE
    status: FuzzRunStatus = FuzzRunStatus.PENDING
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ConversationNode(SQLModel, table=True):
    """One external turn of a TreeRun's clean backbone -- just enough to
    replay the same external message sequence for a probe attempt.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    tree_run_id: int = Field(foreign_key="treerun.id", index=True)
    turn_index: int
    message_sent: str
    agent_reply: str
    created_at: datetime = Field(default_factory=utcnow)


class InjectionProbe(SQLModel, table=True):
    """One fuzzing attempt at one backbone checkpoint (a tool-result
    occurrence) -- run to its own natural completion, never injected a
    second time. A TreeRun with attempts_per_checkpoint=5 produces up to 5
    of these per checkpoint.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    tree_run_id: int = Field(foreign_key="treerun.id", index=True)
    checkpoint_occurrence: int
    attempt_index: int
    seed_template_id: int = Field(foreign_key="injectiontemplate.id")
    template_id: int = Field(foreign_key="injectiontemplate.id")
    campaign_id: int = Field(foreign_key="campaign.id")
    tool_name: str = ""
    original_tool_result: str = ""
    injected_tool_result: str = ""
    trajectory: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    stopped_reason: str = ""
    detector_success: bool = False
    judge_score: float = 0.0
    judge_verdict: str = ""
    reward: float = 0.0
    success: bool = False
    diverged_from_backbone: bool = False
    divergence_detail: str = ""
    created_at: datetime = Field(default_factory=utcnow)
