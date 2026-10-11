from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from app.models import (
    EventDirection,
    InjectionTrialStatus,
    InjectionVerdict,
    InteractionMode,
    ProviderType,
    ScanLogLevel,
    ScanStatus,
)


class LLMModelCreate(BaseModel):
    name: str
    provider_type: ProviderType = ProviderType.OPENAI
    base_url: str
    api_key: str
    model: str = "gpt-4o-mini"


class LLMModelRead(BaseModel):
    id: int
    name: str
    provider_type: ProviderType
    base_url: str
    api_key_masked: str
    model: str
    created_at: str


class LLMModelUpdate(BaseModel):
    name: Optional[str] = None
    provider_type: Optional[ProviderType] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


class AgentConfigCreate(BaseModel):
    name: str
    git_repo_url: str
    git_ref: str = "main"
    git_access_token: Optional[str] = None
    dockerfile_path: str = "Dockerfile"
    env_example_path: Optional[str] = None
    api_port: Optional[int] = None
    entrypoint: Optional[list[str]] = None
    env_vars: dict[str, str] = {}
    resources: Optional[dict] = None
    agent_purpose: Optional[str] = None
    interaction_mode: InteractionMode = InteractionMode.NONE
    api_config: Optional[dict] = None
    langgraph_config: Optional[dict] = None


class AgentConfigUpdate(BaseModel):
    name: Optional[str] = None
    git_repo_url: Optional[str] = None
    git_ref: Optional[str] = None
    git_access_token: Optional[str] = None
    dockerfile_path: Optional[str] = None
    env_example_path: Optional[str] = None
    api_port: Optional[int] = None
    entrypoint: Optional[list[str]] = None
    env_vars: Optional[dict[str, str]] = None
    resources: Optional[dict] = None
    agent_purpose: Optional[str] = None
    interaction_mode: Optional[InteractionMode] = None
    api_config: Optional[dict] = None
    langgraph_config: Optional[dict] = None


class MCPRemoteTarget(BaseModel):
    kind: Literal["remote"]
    server_url: HttpUrl
    transport: Literal["auto", "streamable_http", "sse"] = "auto"
    headers: dict[str, str] = Field(default_factory=dict)
    verify_tls: bool = True

    @field_validator("headers")
    @classmethod
    def validate_headers(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for name, header_value in value.items():
            clean_name = name.strip()
            if not clean_name:
                raise ValueError("header name must not be empty")
            normalized[clean_name] = header_value
        return normalized


class MCPRepositoryTarget(BaseModel):
    kind: Literal["repository"]
    git_repo_url: str = Field(min_length=1)
    git_ref: str = Field(default="main", min_length=1)
    git_access_token: Optional[str] = None
    config_path: str = Field(default="mcp_config.json", min_length=1)
    env: dict[str, str] = Field(default_factory=dict)

    @field_validator("git_repo_url", "git_ref", "config_path")
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be empty")
        return value


class MCPBundleTarget(BaseModel):
    kind: Literal["bundle"]
    artifact_id: int = Field(gt=0)
    user_config: dict[str, Any] = Field(default_factory=dict)


class MCPSnapshotTarget(BaseModel):
    kind: Literal["snapshot"]
    tools: dict


class MCPSourceTarget(BaseModel):
    kind: Literal["source"]
    files: dict[str, str]


MCPTarget = Annotated[
    Union[MCPRemoteTarget, MCPRepositoryTarget, MCPBundleTarget, MCPSnapshotTarget, MCPSourceTarget],
    Field(discriminator="kind"),
]


class MCPScanConfig(BaseModel):
    """Description of an MCP target consumed by future scan stages.

    An empty scanner_ids list means "run every scanner available in the
    service". This keeps scan creation independent from the scanner catalogue
    while that service is being implemented.
    """

    target: MCPTarget
    probes: list[dict] = Field(default_factory=list)
    allow_tool_calls: bool = False
    allow_cloud: bool = False
    scanner_ids: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=30, ge=1, le=300)

    @model_validator(mode="before")
    @classmethod
    def upgrade_legacy_remote_config(cls, value: Any) -> Any:
        """Accept configs created by the first remote-only UI revision."""
        if isinstance(value, dict) and "target" not in value and "server_url" in value:
            legacy = dict(value)
            target = {
                "kind": "remote",
                "server_url": legacy.pop("server_url"),
                "transport": legacy.pop("transport", "auto"),
                "headers": legacy.pop("headers", {}),
                "verify_tls": legacy.pop("verify_tls", True),
            }
            legacy["target"] = target
            return legacy
        return value

    @field_validator("scanner_ids")
    @classmethod
    def normalize_scanner_ids(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(scanner_id.strip() for scanner_id in value if scanner_id.strip()))


class MCPArtifactFromURL(BaseModel):
    url: HttpUrl
    expected_sha256: Optional[str] = None

    @field_validator("url")
    @classmethod
    def require_https(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("разрешены только HTTPS URI")
        return value

    @field_validator("expected_sha256")
    @classmethod
    def validate_expected_sha256(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        value = value.strip().lower()
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("expected_sha256 должен содержать 64 hex-символа")
        return value


class MCPArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_filename: str
    source_type: str
    source_url: Optional[str]
    sha256: str
    size_bytes: int
    manifest: dict
    created_at: datetime


class ScanUpdate(BaseModel):
    status: Optional[ScanStatus] = None
    phase: Optional[str] = None
    error: Optional[str] = None
    results: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    agent_namespace: Optional[str] = None
    agent_pod_name: Optional[str] = None
    build_job_name: Optional[str] = None
    built_image: Optional[str] = None


class ScanLogCreate(BaseModel):
    level: ScanLogLevel = ScanLogLevel.INFO
    phase: Optional[str] = None
    message: str


class TrafficEventRead(BaseModel):
    """Event metadata for the list view -- deliberately without the body so
    a long events table stays light."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    scan_id: Optional[int] = None
    flow_id: str
    direction: EventDirection
    provider: str
    host: str
    path: str
    upstream_base_url: Optional[str] = None
    trial_id: Optional[int] = None
    injected: bool = False
    injection_target: Optional[str] = None
    created_at: datetime


class InjectionTrialCreate(BaseModel):
    injection_point: str = "tool_result"
    baseline: bool = False
    task_index: int = 0
    task: str = ""
    target_tool: Optional[str] = None
    occurrence: int = 1
    mode: str = "append"
    payload_name: Optional[str] = None
    payload_family: Optional[str] = None
    payload_text: Optional[str] = None
    canary: Optional[str] = None


class InjectionTrialUpdate(BaseModel):
    status: Optional[InjectionTrialStatus] = None
    injected_count: Optional[int] = None
    verdict: Optional[InjectionVerdict] = None
    verdict_reason: Optional[str] = None
    agent_response: Optional[str] = None
    baseline_response: Optional[str] = None
    finished_at: Optional[datetime] = None


class TrafficEventDetail(TrafficEventRead):
    raw_excerpt: str = ""


class TrafficEventDetailResponse(BaseModel):
    """One event plus its counterpart in the same flow (the request for a
    response, or vice versa), so the UI can show a whole exchange at once."""

    event: TrafficEventDetail
    pair: Optional[TrafficEventDetail] = None
