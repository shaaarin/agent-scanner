from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON, Text
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProviderType(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class LLMModel(SQLModel, table=True):
    """A real LLM client entered via the web UI: a provider + model + base
    URL + API key. Used for DeepTeam evaluation (LLM-as-a-Judge) via LiteLLM,
    so any provider LiteLLM supports works.

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
    git_access_token: Optional[str] = (
        None  # PAT for private HTTPS repos -- see launcher/app/git_auth.py. Plain text, same accepted MVP tech debt as LLMModel.api_key.
    )
    dockerfile_path: str = "Dockerfile"  # path to the Dockerfile, relative to the repo root (build context is always the repo root)
    env_example_path: Optional[str] = (
        None  # e.g. ".env.example" -- launcher reads this to auto-fill env_vars with the repo's own declared defaults
    )
    api_port: Optional[int] = (
        None  # container port the agent listens on, if any -- launcher exposes it via an auto-created NodePort Service
    )
    entrypoint: Optional[list[str]] = Field(default=None, sa_column=Column(JSON))
    env_vars: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    resources: Optional[dict] = Field(
        default=None, sa_column=Column(JSON)
    )  # e.g. {"cpu": "500m", "memory": "512Mi"}
    # Назначение агента своими словами: DeepTeam строит по нему атаки и
    # оценивает ответы (purpose / target_purpose).
    agent_purpose: Optional[str] = Field(default=None, sa_column=Column(Text))
    interaction_mode: InteractionMode = InteractionMode.NONE
    # api_config (interaction_mode=api): {"url", "method", "body_format",
    #   "request_body_template" (with "{{message}}"/"{{session_id}}"
    #   placeholders), "response_field" (dot-path into the JSON response, e.g.
    #   "reply" or "messages.-1.content"), "headers", "health_path"} -- see
    #   scanner/deepteam/app/target.py.
    api_config: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    # langgraph_config (interaction_mode=langgraph): {"base_url", "assistant_id",
    #   "api_key" (optional, sent as X-Api-Key for LangGraph Platform deployments)}.
    langgraph_config: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class EventDirection(str, Enum):
    REQUEST = "request"
    RESPONSE = "response"


class TrafficEvent(SQLModel, table=True):
    """Every intercepted request/response the proxy reports back. The full
    body is kept in `raw_excerpt` so the events page can show exactly what the
    agent sent/received (not just that a call happened)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    scan_id: Optional[int] = None  # References Scan instead of Campaign
    flow_id: str = Field(index=True)
    direction: EventDirection
    provider: str = "openai"
    host: str = ""
    path: str = ""
    # Exact request/response body the proxy forwarded, stored untruncated.
    raw_excerpt: str = Field(default="", sa_column=Column(Text))
    # Real upstream the agent dialed (scheme://host[:port]), for context.
    upstream_base_url: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class ScanType(str, Enum):
    """Каждый реализованный тип выполняет свой сервис-сканер (см.
    `app/api/scans.py::SCANNERS`). Колонка `scan.type` строковая, поэтому новый
    тип не требует миграции."""

    DEEP_TEAM = "deep_team"  # scanner-deepteam: динамическое тестирование
    CODE_SCAN = "code_scan"  # scanner-promptfoo: анализ исходного кода
    MCP = "mcp"  # заглушка в UI, сканера пока нет
    AGENT_SKILLS = "agent_skills"  # заглушка в UI, сканера пока нет


class ScanStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Scan(SQLModel, table=True):
    """Security scan configuration for an agent: DeepTeam red teaming,
    MCP testing, or Agent Skills assessment.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    type: ScanType
    agent_config_id: int = Field(foreign_key="agentconfig.id", index=True)
    status: ScanStatus = ScanStatus.PENDING
    session_id: str = Field(index=True)  # Links scan to proxy session
    # JSON config specific to scan type:
    # - DEEP_TEAM: {"eval_llm_model_id": int, "vulnerabilities": [...], "attacks": [...]}
    # - CODE_SCAN: {"min_severity": "low|medium|high|critical", "guidance": str | null}
    # - MCP: {} (placeholder)
    # - AGENT_SKILLS: {} (placeholder)
    config: str = Field(default="{}", sa_column=Column(JSON))
    # JSON results, shape depends on type:
    # - DEEP_TEAM: {"vulnerability_results": [...], "overall_score": float}
    # - CODE_SCAN: {"engine": "promptfoo-code-scans", "summary": {...}, "findings": [...], ...}
    results: Optional[str] = Field(default=None, sa_column=Column(JSON))
    # High-level progress state, written by scanner as it moves through phases
    # ("Инициализация", "Запуск агента", ...). The detailed per-line log lives
    # in ScanLog -- see /scans/{id}/logs.
    phase: Optional[str] = None
    error: Optional[str] = None
    # Launch metadata, written by launcher once the tested agent's Pod exists
    # (mirrors what Campaign carried before the Scan refactor).
    agent_namespace: Optional[str] = None
    agent_pod_name: Optional[str] = None
    build_job_name: Optional[str] = None
    built_image: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class ScanLogLevel(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    ERROR = "error"


class ScanLog(SQLModel, table=True):
    """One line in a scan's live progress log, appended by the scanner (or
    control-api itself for start/launch failures) and polled by the scan
    detail page. Ordered by autoincrementing id, so the UI can poll
    `GET /scans/{id}/logs?after_id=<last seen>` for cheap incremental updates.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    scan_id: int = Field(foreign_key="scan.id", index=True)
    level: ScanLogLevel = ScanLogLevel.INFO
    phase: Optional[str] = None
    message: str
    created_at: datetime = Field(default_factory=utcnow)
