from typing import Optional

from pydantic import BaseModel

from app.models import (
    CampaignStatus,
    FuzzMode,
    FuzzRunStatus,
    InjectionMode,
    InjectionTarget,
    InjectionTemplate,
    InteractionMode,
    InteractorPersona,
    ProviderType,
    SuccessIndicatorField,
)


class InjectionTemplateCreate(BaseModel):
    name: str
    description: str = ""
    target: InjectionTarget
    mode: InjectionMode = InjectionMode.APPEND
    payload: str
    success_indicator: Optional[str] = None
    success_indicator_field: SuccessIndicatorField = SuccessIndicatorField.TOOL_NAME
    tags: list[str] = []


class InjectionTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    target: Optional[InjectionTarget] = None
    mode: Optional[InjectionMode] = None
    payload: Optional[str] = None
    success_indicator: Optional[str] = None
    success_indicator_field: Optional[SuccessIndicatorField] = None
    tags: Optional[list[str]] = None


class CampaignCreate(BaseModel):
    name: str
    session_id: str
    template_id: int
    status: CampaignStatus = CampaignStatus.PAUSED
    injection_rate: float = 1.0
    inject_at_occurrence: Optional[int] = None
    agent_config_id: Optional[int] = None
    interactor_llm_model_id: Optional[int] = None
    generator_llm_model_id: Optional[int] = None
    interactor_persona: Optional[InteractorPersona] = None
    user_instruction: Optional[str] = None


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[CampaignStatus] = None
    injection_rate: Optional[float] = None
    inject_at_occurrence: Optional[int] = None
    agent_config_id: Optional[int] = None
    interactor_llm_model_id: Optional[int] = None
    generator_llm_model_id: Optional[int] = None
    interactor_persona: Optional[InteractorPersona] = None
    user_instruction: Optional[str] = None
    agent_namespace: Optional[str] = None
    agent_pod_name: Optional[str] = None
    build_job_name: Optional[str] = None
    built_image: Optional[str] = None


class LLMModelCreate(BaseModel):
    name: str
    provider_type: ProviderType = ProviderType.OPENAI
    base_url: str
    api_key: str
    model: str = "gpt-4o-mini"


class LLMModelUpdate(BaseModel):
    name: Optional[str] = None
    provider_type: Optional[ProviderType] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


class LLMModelRead(BaseModel):
    """Redacted shape used for list responses -- api_key is masked."""

    id: int
    name: str
    provider_type: ProviderType
    base_url: str
    api_key_masked: str
    model: str


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


class TrafficEventCreate(BaseModel):
    session_id: str
    campaign_id: Optional[int] = None
    flow_id: str
    direction: str
    provider: str = "openai"
    host: str = ""
    path: str = ""
    injected: bool = False
    injection_target: Optional[str] = None
    success_detected: bool = False
    detail: str = ""
    raw_excerpt: str = ""


class FuzzRunCreate(BaseModel):
    name: str
    base_campaign_id: int
    injection_target: InjectionTarget
    mode: FuzzMode = FuzzMode.NON_ADAPTIVE
    seed_template_ids: list[int] = []
    judge_llm_model_id: Optional[int] = None
    max_iterations: int = 20
    stop_on_success: bool = True


class FuzzRunUpdate(BaseModel):
    status: Optional[FuzzRunStatus] = None
    success_attempt_id: Optional[int] = None


class FuzzAttemptCreate(BaseModel):
    iteration: int
    seed_template_id: int
    template_id: int
    campaign_id: int
    mutation_strategy: str = ""
    detector_success: bool = False
    judge_score: float = 0.0
    judge_verdict: str = ""
    reward: float = 0.0
    success: bool = False


class ActiveCampaignResponse(BaseModel):
    campaign_id: int
    session_id: str
    status: CampaignStatus
    injection_rate: float
    inject_at_occurrence: Optional[int] = None
    template: InjectionTemplate
    template_id: int


class TreeRunCreate(BaseModel):
    name: str
    base_campaign_id: int
    seed_template_ids: list[int] = []
    judge_llm_model_id: Optional[int] = None
    max_backbone_turns: int = 10
    max_probe_turns: int = 10
    max_checkpoints: Optional[int] = None
    attempts_per_checkpoint: int = 5
    mode: FuzzMode = FuzzMode.NON_ADAPTIVE


class TreeRunUpdate(BaseModel):
    status: Optional[FuzzRunStatus] = None


class ConversationNodeCreate(BaseModel):
    turn_index: int
    message_sent: str
    agent_reply: str


class InjectionProbeCreate(BaseModel):
    checkpoint_occurrence: int
    attempt_index: int
    seed_template_id: int
    template_id: int
    campaign_id: int
    tool_name: str = ""
    original_tool_result: str = ""
    injected_tool_result: str = ""
    trajectory: list[dict] = []
    stopped_reason: str = ""
    detector_success: bool = False
    judge_score: float = 0.0
    judge_verdict: str = ""
    reward: float = 0.0
    success: bool = False
    diverged_from_backbone: bool = False
    divergence_detail: str = ""
