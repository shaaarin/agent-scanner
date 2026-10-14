from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON, LargeBinary, String, Text
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


class AgentSource(str, Enum):
    """Откуда берётся тестируемый агент:
    - repository -- собирается платформой из git (launcher: clone + Kaniko +
      Pod с MITM-сайдкаром);
    - remote -- уже запущен вне платформы, сборка не нужна: платформа ходит
      напрямую по `remote_base_url` (+ `remote_token` как Authorization).
      Трафик такого агента к LLM через прокси платформы не проходит."""

    REPOSITORY = "repository"
    REMOTE = "remote"


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
    # Колонка строковая и хранит значения ('repository'/'remote'), как
    # Scan.asset_kind -- иначе расходятся ORM, миграция и строковые фильтры.
    source: AgentSource = Field(
        default=AgentSource.REPOSITORY,
        sa_column=Column(String, nullable=False, server_default="repository"),
    )
    # source=repository: агент собирается платформой из git.
    git_repo_url: Optional[str] = None
    git_ref: str = "main"
    git_access_token: Optional[str] = (
        None  # PAT for private HTTPS repos -- see launcher/app/git_auth.py. Plain text, same accepted MVP tech debt as LLMModel.api_key.
    )
    # source=remote: уже запущенный агент. Адрес (scheme://host[:port]),
    # эндпоинт и тело запроса -- в api_config/langgraph_config; заголовки
    # авторизации -- произвольные пары «имя: значение» (например,
    # Authorization: Bearer ... или X-API-Key). Plain text, тот же принятый
    # техдолг MVP, что и остальные креды.
    remote_base_url: Optional[str] = None
    remote_headers: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
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
    # Indirect-injection scans only: which InjectionTrial this exchange
    # belongs to, and whether the proxy rewrote the outgoing body for it (and
    # into which tool result). The proxy already reported `injected`/
    # `injection_target`; before this they were dropped on the floor.
    trial_id: Optional[int] = Field(default=None, index=True)
    injected: bool = False
    injection_target: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class AssetKind(str, Enum):
    """Виды активов раздела «Активы». Активы агентов хранятся как `AgentConfig`,
    MCP-цели -- `McpAsset`, skills -- `SkillAsset`; объединяет их реестр
    сканеров (`app/scanner_registry.py`), где для каждого сканера указано,
    на каких видах активов он работает."""

    AGENT = "agent"
    MCP = "mcp"
    SKILL = "skill"


class McpAsset(SQLModel, table=True):
    """Актив «MCP»: цель тестирования -- работающий сервер, git-репозиторий
    или загруженный MCPB-архив (см. `MCPTarget` в app/schemas.py). При
    создании скана control-api копирует `config` в `Scan.config.target`, так
    что контракт scanner-mcp не меняется, а правки актива не переписывают
    уже созданные сканы."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    # Форма MCPTarget: {"kind": "remote|repository|bundle", ...}
    config: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # Необязательные настройки деплоя для динамического сканирования
    # (запуск сервера из репозитория/MCPB): {"port": int, "command": str,
    # "env": {...}}. Заполнены -- только если пользователь их задал.
    deploy: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class SkillSource(str, Enum):
    REPOSITORY = "repository"
    ZIP = "zip"


class SkillAsset(SQLModel, table=True):
    """Актив «Skill»: набор skills агента из git-репозитория или zip-архива.
    Сканирует его `scanner-skills` (тип `agent_skills`); при создании скана
    control-api копирует источник в `Scan.config.source`."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    source: SkillSource = SkillSource.REPOSITORY
    # source=repository: HTTPS-репозиторий (токен -- принятый техдолг MVP,
    # как AgentConfig.git_access_token).
    git_repo_url: Optional[str] = None
    git_ref: Optional[str] = None
    git_access_token: Optional[str] = None
    # source=zip: архив хранится BLOB-ом (по образцу MCPArtifact).
    archive_filename: Optional[str] = None
    archive_sha256: Optional[str] = Field(default=None, index=True)
    archive: Optional[bytes] = Field(default=None, sa_column=Column(LargeBinary))
    created_at: datetime = Field(default_factory=utcnow)


class ScanType(str, Enum):
    """Каждый реализованный тип выполняет свой сервис-сканер (см.
    `app/api/scans.py::SCANNERS`). Колонка `scan.type` строковая, поэтому новый
    тип не требует миграции."""

    DEEP_TEAM = "deep_team"  # scanner-deepteam: динамическое тестирование
    PYRIT_SCAN = "pyrit_scan"  # scanner-pyrit: red teaming через Microsoft PyRIT
    CODE_SCAN = "code_scan"  # scanner-promptfoo: анализ исходного кода
    AI_CODE_SCAN = "ai_code_scan"  # scanner-semgrep: локальный semgrep AI-правил по коду агента
    INDIRECT_INJECTION = "indirect_injection"  # scanner-indirect: косвенные инъекции в результаты инструментов
    SYSTEM_PROMPT_LEAK = "system_prompt_leak"  # scanner-sysleak: утечка системного промпта
    MCP = "mcp"  # scanner-mcp: metadata, dynamic and SAST
    AGENT_SKILLS = "agent_skills"  # scanner-skills: статический анализ Agent Skills (SKILL.md)


class ScanStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SUCCESS = "success"
    PARTIALLY_FAILED = "partially_failed"
    FAILED = "failed"


class MCPArtifact(SQLModel, table=True):
    """An immutable MCPB uploaded by the user or materialized from HTTPS.

    The archive stays as a BLOB in PostgreSQL for the MVP. List/read schemas never
    expose ``content``; a future scanner-mcp service will request it through a
    dedicated endpoint immediately before scanning.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    original_filename: str
    source_type: str  # upload | url
    source_url: Optional[str] = None
    sha256: str = Field(index=True)
    size_bytes: int
    manifest: dict = Field(default_factory=dict, sa_column=Column(JSON))
    content: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)


class Scan(SQLModel, table=True):
    """Security scan configuration for an agent: DeepTeam red teaming,
    MCP testing, or Agent Skills assessment.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    type: ScanType
    # A retry is a separate scan: previous reports and logs remain immutable.
    retry_of_scan_id: Optional[int] = Field(default=None, foreign_key="scan.id", index=True)
    retry_root_scan_id: Optional[int] = Field(default=None, foreign_key="scan.id", index=True)
    retry_mode: Optional[str] = None  # all | failed | engine
    # Ссылка на актив из раздела «Активы» (см. AssetKind). Для агентов
    # дублируется в agent_config_id: все сканеры и launcher читают только его.
    # Колонка строковая и хранит ЗНАЧЕНИЯ ('agent'/'mcp'/'skill') -- иначе
    # строковые фильтры API и backfill миграции расходились бы с ORM.
    asset_kind: Optional[AssetKind] = Field(
        default=None, sa_column=Column(String, nullable=True, index=True)
    )
    asset_id: Optional[int] = Field(default=None, index=True)
    # Agent-backed scans (deep_team, code_scan) require this reference at the
    # API level. Remote targets such as an MCP server do not have an
    # AgentConfig, so the database relationship itself is optional.
    agent_config_id: Optional[int] = Field(default=None, foreign_key="agentconfig.id", index=True)
    status: ScanStatus = ScanStatus.PENDING
    session_id: str = Field(index=True)  # Links scan to proxy session
    # JSON config specific to scan type:
    # - DEEP_TEAM: {"eval_llm_model_id": int, "vulnerabilities": [...], "attacks": [...]}
    # - PYRIT_SCAN: {"eval_llm_model_id": int, "objectives": [str], "strategies": [str],
    #                "converters": [str], "max_turns": int}
    # - CODE_SCAN: {"min_severity": "low|medium|high|critical", "guidance": str | null}
    # - AI_CODE_SCAN: {"min_severity": "low|medium|high", "rule_sets": [str],
    #                  "custom_rules": str | null}
    # - INDIRECT_INJECTION: {"tasks": [str], "target_tools": [str], "payloads": [str],
    #                        "repeats": int, "max_trials": int}
    # - MCP: {"target": {"kind": "remote|repository|bundle", ...},
    #         "scanner_ids": [...], "timeout_seconds": int}
    # - AGENT_SKILLS: {"engines": [str], ...поля /schema scanner-skills,
    #                  "source": {"kind": "zip", "asset_id", "archive_filename", "archive_sha256"}
    #                          | {"kind": "repository", "git_repo_url", "git_ref", "git_access_token"}}
    config: str = Field(default="{}", sa_column=Column(JSON))
    # JSON results, shape depends on type:
    # - DEEP_TEAM: {"vulnerability_results": [...], "overall_score": float}
    # - PYRIT_SCAN: {"vulnerability_results": [...], "overall_score": float}
    # - CODE_SCAN: {"engine": "promptfoo-code-scans", "summary": {...}, "findings": [...], ...}
    # - AI_CODE_SCAN: {"engine": "semgrep", "summary": {...}, "findings": [...], ...}
    # - INDIRECT_INJECTION: {"engine": "indirect-injection", "summary": {...},
    #                        "by_tool": [...], "by_payload": [...], "trials": [...]}
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


class InjectionTrialStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"  # сейчас выполняется -- именно её директиву отдаёт прокси
    DONE = "done"
    ERROR = "error"


class InjectionVerdict(str, Enum):
    ROBUST = "robust"  # инъекция подложена, но агент ей не поддался (для sysleak -- не утёк)
    VULNERABLE = "vulnerable"  # агент выполнил инструкцию (для sysleak -- системный промпт утёк)
    INCONCLUSIVE = "inconclusive"  # подложить было некуда (нет вызова инструмента / не вставилась метка)
    ERROR = "error"


class InjectionPoint(str, Enum):
    """Куда прокси подкладывает по директиве активного прогона:
    - TOOL_RESULT -- в результат инструмента (`role: tool`), скан indirect_injection;
    - SYSTEM_PROMPT -- в системное сообщение (`role: system`), скан system_prompt_leak.
    """

    TOOL_RESULT = "tool_result"
    SYSTEM_PROMPT = "system_prompt"


class InjectionTrial(SQLModel, table=True):
    """Один прогон агента для сканов, где прокси подменяет тело запроса по
    активной директиве (`GET /scans/{id}/injection/active`). Прогоны идут
    последовательно, поэтому `RUNNING`-прогон в скане всегда ровно один.

    Два вида инъекции (`injection_point`):
    - `tool_result` (indirect_injection) -- агенту шлётся легитимная задача
      (`task`), прокси дописывает `payload_text` в результат инструмента
      `target_tool`; `baseline=True` -- прогон без инъекции для поиска вызовов;
    - `system_prompt` (system_prompt_leak) -- агенту шлётся атакующий промпт
      (`payload_text`), прокси вставляет метку `canary` в системное сообщение;
      утечка = метка всплыла в ответе агента.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    scan_id: int = Field(foreign_key="scan.id", index=True)
    injection_point: InjectionPoint = InjectionPoint.TOOL_RESULT
    baseline: bool = False
    task_index: int = 0
    task: str = Field(default="", sa_column=Column(Text))
    # Куда подкладывать: имя инструмента (или "*" -- любой) и какой по счёту
    # его вызов. Для baseline и для system_prompt -- None.
    target_tool: Optional[str] = None
    occurrence: int = 1
    mode: str = "append"  # append | prepend | replace
    payload_name: Optional[str] = None
    payload_family: Optional[str] = None
    payload_text: Optional[str] = Field(default=None, sa_column=Column(Text))
    # Контрольная метка этого прогона: если она всплыла в ответе агента или в
    # аргументах его вызова инструмента -- значит агент поддался инъекции.
    canary: Optional[str] = None
    status: InjectionTrialStatus = InjectionTrialStatus.PENDING
    injected_count: int = 0  # сколько раз прокси реально применил подстановку
    verdict: Optional[InjectionVerdict] = None
    verdict_reason: Optional[str] = Field(default=None, sa_column=Column(Text))
    agent_response: Optional[str] = Field(default=None, sa_column=Column(Text))
    baseline_response: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None
