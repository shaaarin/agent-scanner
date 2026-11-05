from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from app.models import (
    AgentSource,
    AssetKind,
    EventDirection,
    InjectionTrialStatus,
    InjectionVerdict,
    InteractionMode,
    OrgRole,
    ProviderType,
    ScanLogLevel,
    ScanStatus,
    ScanType,
    SkillSource,
)


class LLMModelCreate(BaseModel):
    name: str
    organization_id: int = Field(gt=0)
    provider_type: ProviderType = ProviderType.OPENAI
    base_url: str
    api_key: str
    model: str = "gpt-4o-mini"


class LLMModelRead(BaseModel):
    id: int
    organization_id: int
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


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1)
    description: Optional[str] = None


class OrganizationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str]
    created_at: datetime
    # Роль вызвавшего пользователя в этой организации (None -- не участник,
    # например системный админ или машинный контур).
    my_role: Optional[OrgRole] = None
    members_count: int = 0


class MemberCreate(BaseModel):
    """Приглашение участника по логину платформы. Если пользователя с таким
    логином ещё нет, он создаётся «тихо» и пароль задаёт при регистрации
    (или сразу -- через необязательный `password`)."""

    login: str = Field(min_length=1)
    role: OrgRole = OrgRole.READER
    password: Optional[str] = None


class MemberUpdate(BaseModel):
    role: OrgRole


class InviteCreate(BaseModel):
    """Создание одноразовой ссылки-приглашения (admin организации)."""

    role: OrgRole = OrgRole.READER


class InviteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: OrgRole
    token: str  # секрет в URL: /invite/<token>
    created_at: datetime
    used: bool


class InviteInfo(BaseModel):
    """Публичная информация по ссылке (для страницы приглашения, без auth)."""

    org_name: str
    role: OrgRole
    valid: bool


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    login: str
    display_name: Optional[str]
    email: Optional[str]
    is_superadmin: bool = False
    role: OrgRole
    last_login_at: Optional[datetime] = None


class AgentConfigCreate(BaseModel):
    name: str
    organization_id: int = Field(gt=0)
    source: AgentSource = AgentSource.REPOSITORY
    # source=repository: сборка платформой из git.
    git_repo_url: Optional[str] = None
    git_ref: str = "main"
    git_access_token: Optional[str] = None
    dockerfile_path: str = "Dockerfile"
    env_example_path: Optional[str] = None
    api_port: Optional[int] = None
    entrypoint: Optional[list[str]] = None
    env_vars: dict[str, str] = {}
    resources: Optional[dict] = None
    # source=remote: уже запущенный агент вне платформы.
    remote_base_url: Optional[str] = None
    # Заголовки авторизации произвольными парами «имя: значение»
    remote_headers: dict[str, str] = {}
    agent_purpose: Optional[str] = None
    interaction_mode: InteractionMode = InteractionMode.NONE
    api_config: Optional[dict] = None
    langgraph_config: Optional[dict] = None

    @model_validator(mode="after")
    def require_source_fields(self) -> "AgentConfigCreate":
        if self.source == AgentSource.REPOSITORY and not (self.git_repo_url or "").strip():
            raise ValueError("для источника «repository» нужен git_repo_url")
        if self.source == AgentSource.REMOTE:
            base = (self.remote_base_url or "").strip()
            if not base.lower().startswith(("http://", "https://")):
                raise ValueError("для источника «remote» нужен remote_base_url (http:// или https://)")
        return self


class AgentConfigUpdate(BaseModel):
    name: Optional[str] = None
    source: Optional[AgentSource] = None
    git_repo_url: Optional[str] = None
    git_ref: Optional[str] = None
    git_access_token: Optional[str] = None
    dockerfile_path: Optional[str] = None
    env_example_path: Optional[str] = None
    api_port: Optional[int] = None
    entrypoint: Optional[list[str]] = None
    env_vars: Optional[dict[str, str]] = None
    resources: Optional[dict] = None
    remote_base_url: Optional[str] = None
    remote_headers: Optional[dict[str, str]] = None
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
    auto_probes: bool = False
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
    organization_id: int = Field(gt=0)
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
    organization_id: int
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


class ScanRetry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["all", "failed", "engine"] = "all"
    engine_id: Optional[str] = None

    @model_validator(mode="after")
    def require_engine(self):
        if (self.mode == "engine") != (self.engine_id is not None):
            raise ValueError("engine_id задаётся только для перезапуска отдельного движка")
        return self


class ScanCreate(BaseModel):
    """Создание скана из UI: всегда внутри актива. Параметры сканера
    (`config`) валидируются по реестру сканеров, статус/результаты клиент
    задавать не может."""

    name: str = Field(min_length=1)
    type: ScanType
    asset_kind: AssetKind
    asset_id: int = Field(gt=0)
    session_id: str = Field(min_length=1)
    # Параметры выбранного сканера (поля -- из GET /scanners config_schema).
    # Для MCP цель подставляется из актива, здесь только scanner_ids и т.п.
    config: dict = Field(default_factory=dict)


class McpDeploySettings(BaseModel):
    """Необязательные настройки деплоя MCP-актива для динамического
    сканирования: как поднять сервер из репозитория/MCPB. Заполнение не
    влияет на существующие движки -- данные под грядущий деплой."""

    port: Optional[int] = Field(default=None, ge=1, le=65535)
    dockerfile_path: Optional[str] = None  # сборка образа сервера, как у агентов
    mcp_path: Optional[str] = None  # путь MCP-эндпоинта, например /mcp
    command: Optional[str] = None
    env: dict[str, str] = Field(default_factory=dict)


class McpAssetCreate(BaseModel):
    name: str = Field(min_length=1)
    organization_id: int = Field(gt=0)
    description: Optional[str] = None
    # Форма MCPTarget (remote/repository/bundle); source/snapshot как цели
    # сканов не используются -- это режимы ad-hoc проверок.
    config: MCPTarget
    deploy: Optional[McpDeploySettings] = None


class McpAssetUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[MCPTarget] = None
    deploy: Optional[McpDeploySettings] = None


class SkillAssetCreate(BaseModel):
    name: str = Field(min_length=1)
    organization_id: int = Field(gt=0)
    description: Optional[str] = None
    source: SkillSource = SkillSource.REPOSITORY
    git_repo_url: Optional[str] = None
    git_ref: Optional[str] = "main"
    git_access_token: Optional[str] = None

    @model_validator(mode="after")
    def require_source_fields(self) -> "SkillAssetCreate":
        if self.source == SkillSource.REPOSITORY and not (self.git_repo_url or "").strip():
            raise ValueError("для источника «repository» нужен git_repo_url")
        return self


class SkillAssetUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    git_repo_url: Optional[str] = None
    git_ref: Optional[str] = None
    git_access_token: Optional[str] = None


class SkillAssetRead(BaseModel):
    """Ответ API без бинарного архива."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    name: str
    description: Optional[str]
    source: SkillSource
    git_repo_url: Optional[str]
    git_ref: Optional[str]
    archive_filename: Optional[str]
    archive_sha256: Optional[str]
    created_at: datetime


class AssetRead(BaseModel):
    """Единая запись раздела «Активы» (объединяет три вида)."""

    kind: AssetKind
    id: int
    name: str
    organization_id: int
    description: Optional[str] = None
    created_at: datetime


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
