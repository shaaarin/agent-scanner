from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

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
