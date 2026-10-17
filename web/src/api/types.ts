export type ProviderType = "openai" | "anthropic";
export type InteractionMode = "none" | "api" | "langgraph";
export type AgentSource = "repository" | "remote";

export interface TrafficEvent {
  id: number;
  session_id: string;
  scan_id: number | null;
  flow_id: string;
  direction: "request" | "response";
  provider: string;
  host: string;
  path: string;
  upstream_base_url: string | null;
  created_at: string;
}

export interface TrafficEventDetail extends TrafficEvent {
  raw_excerpt: string;
}

export interface TrafficEventDetailResponse {
  event: TrafficEventDetail;
  pair: TrafficEventDetail | null;
}

export interface LLMModel {
  id: number;
  name: string;
  provider_type: ProviderType;
  base_url: string;
  api_key: string;
  model: string;
}

export interface LLMModelListItem {
  id: number;
  name: string;
  provider_type: ProviderType;
  base_url: string;
  api_key_masked: string;
  model: string;
}

export interface LaunchStatus {
  status: string;
  namespace?: string;
  pod_name?: string;
  built_image?: string;
}

export interface AgentConfig {
  id: number;
  name: string;
  source: AgentSource;
  git_repo_url: string | null;
  git_ref: string;
  git_access_token: string | null;
  remote_base_url: string | null;
  remote_headers: Record<string, string> | null;
  dockerfile_path: string;
  env_example_path: string | null;
  api_port: number | null;
  entrypoint: string[] | null;
  env_vars: Record<string, string>;
  resources: Record<string, string> | null;
  agent_purpose: string | null;
  interaction_mode: InteractionMode;
  api_config: Record<string, unknown> | null;
  langgraph_config: Record<string, unknown> | null;
  created_at: string;
}

export type ScanType = "deep_team" | "pyrit_scan" | "code_scan" | "ai_code_scan" | "indirect_injection" | "system_prompt_leak" | "mcp" | "agent_skills";
export type ScanStatus = "pending" | "running" | "completed" | "failed";
export type AssetKind = "agent" | "mcp" | "skill";

export interface Scan {
  id: number;
  name: string;
  type: ScanType;
  asset_kind: AssetKind | null;
  asset_id: number | null;
  agent_config_id: number | null;
  status: ScanStatus;
  session_id: string;
  config: string; // JSON string
  results: string | null; // JSON string
  phase: string | null;
  error: string | null;
  agent_namespace: string | null;
  agent_pod_name: string | null;
  build_job_name: string | null;
  built_image: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

// Раздел «Активы»: единая запись из GET /assets.
export interface Asset {
  kind: AssetKind;
  id: number;
  name: string;
  description: string | null;
  created_at: string;
}

export interface McpDeploySettings {
  port?: number | null;
  command?: string | null;
  env: Record<string, string>;
}

export interface McpAsset {
  id: number;
  name: string;
  description: string | null;
  config: MCPTarget;
  deploy: McpDeploySettings | null;
  created_at: string;
}

export interface McpAssetCreate {
  name: string;
  description?: string | null;
  config: MCPTarget;
  deploy?: McpDeploySettings | null;
}

export type SkillSource = "repository" | "zip";

export interface SkillAsset {
  id: number;
  name: string;
  description: string | null;
  source: SkillSource;
  git_repo_url: string | null;
  git_ref: string | null;
  archive_filename: string | null;
  archive_sha256: string | null;
  created_at: string;
}

// Реестр сканеров (GET /scanners): UI строит формы создания сканирований
// только из этих данных, никаких списков опций на фронте.
export type ScannerFieldType = "string" | "text" | "text_list" | "integer" | "boolean" | "enum" | "enum_multi" | "llm_model" | "json";

export interface ScannerFieldOption {
  value: string | number;
  label: string;
  available?: boolean;
  cloud?: boolean;
  modes?: string[];
  description?: string;
}

export interface ScannerField {
  name: string;
  label: string;
  type: ScannerFieldType;
  required?: boolean;
  default?: unknown;
  options?: ScannerFieldOption[];
  help?: string;
}

export interface ScannerConfigSchema {
  type: string;
  fields: ScannerField[];
}

export interface ScannerRegistration {
  type: ScanType;
  name: string;
  description: string;
  service: string;
  asset_kinds: AssetKind[];
  phases: string[];
  available: boolean;
  config_schema: ScannerConfigSchema | null;
  // Применимость к конкретному активу (заполнено, когда /scanners вызван
  // с asset_kind+asset_id).
  available_for_asset?: boolean | null;
  unavailable_reason?: string | null;
}

export interface LibraryArticle {
  slug: string;
  category: string;
  title: string;
  summary: string;
  tags: string[];
  source: string;
  date: string;
}

export interface LibraryArticleDetail extends LibraryArticle {
  content: string;
}

export type ScanLogLevel = "info" | "success" | "error";

export interface ScanLog {
  id: number;
  scan_id: number;
  level: ScanLogLevel;
  phase: string | null;
  message: string;
  created_at: string;
}

export type CodeScanSeverity = "critical" | "high" | "medium" | "low";
export type MCPTransport = "auto" | "streamable_http" | "sse";
export type MCPTargetKind = "remote" | "repository" | "bundle";

export interface MCPRemoteTarget {
  kind: "remote";
  server_url: string;
  transport: MCPTransport;
  headers: Record<string, string>;
  verify_tls: boolean;
}

export interface MCPRepositoryTarget {
  kind: "repository";
  git_repo_url: string;
  git_ref: string;
  git_access_token: string | null;
  config_path: string;
  env: Record<string, string>;
}

export interface MCPBundleTarget {
  kind: "bundle";
  artifact_id: number;
  user_config: Record<string, unknown>;
}

export type MCPTarget = MCPRemoteTarget | MCPRepositoryTarget | MCPBundleTarget;

export interface MCPArtifact {
  id: number;
  original_filename: string;
  source_type: "upload" | "url";
  source_url: string | null;
  sha256: string;
  size_bytes: number;
  manifest: Record<string, unknown>;
  created_at: string;
}

export interface ScanConfig {
  // deep_team
  eval_llm_model_id?: number;
  vulnerabilities?: string[];
  attacks?: string[];
  frameworks?: string[];
  // code_scan
  min_severity?: CodeScanSeverity;
  guidance?: string | null;
  // mcp; an empty scanner_ids list means all scanners available in scanner-mcp
  target?: MCPTarget;
  scanner_ids?: string[];
  timeout_seconds?: number;
}

export interface CodeScanFinding {
  file: string | null;
  line: number | null;
  start_line: number | null;
  severity: CodeScanSeverity;
  finding: string;
  fix: string | null;
  ai_agent_prompt: string | null;
}

// Scan.results для type = "code_scan" (пишет scanner-promptfoo) и
// "ai_code_scan" (пишет scanner-semgrep -- тот же формат находок).
export interface CodeScanResults {
  engine: string;
  // Название движка для строки метаданных; по умолчанию "promptfoo".
  engine_label?: string;
  engine_version?: string;
  git_ref?: string;
  commit?: string;
  files_in_scope?: number;
  min_severity?: CodeScanSeverity;
  duration_sec?: number;
  review: string | null;
  summary: Record<CodeScanSeverity, number> & { total: number };
  findings: CodeScanFinding[];
  error?: string;
}

export interface ScanResults {
  vulnerability_results?: Array<{
    vulnerability: string;
    passed: boolean;
    errored?: boolean;
    score: number;
    reasoning: string;
  }>;
  overall_score?: number;
  error?: string;
}

// Scan.results для type = "indirect_injection" (пишет scanner-indirect).
export type InjectionVerdict = "vulnerable" | "robust" | "inconclusive" | "error";

export interface InjectionTrialResult {
  id: number;
  task_index: number;
  target_tool: string | null;
  occurrence: number;
  payload_name: string | null;
  payload_family: string | null;
  verdict: InjectionVerdict;
  verdict_reason: string | null;
  injected_count: number;
  response_excerpt: string;
}

export interface InjectionGroup {
  target_tool?: string;
  payload_name?: string;
  trials: number;
  vulnerable: number;
  robust: number;
  inconclusive: number;
  error: number;
  asr: number;
}

export interface IndirectInjectionResults {
  engine: string;
  summary: {
    tasks: number;
    trials: number;
    injected: number;
    asr: number;
    vulnerable: number;
    robust: number;
    inconclusive: number;
    error: number;
  };
  by_tool: InjectionGroup[];
  by_payload: InjectionGroup[];
  trials: InjectionTrialResult[];
  error?: string;
}

// Scan.results для type = "system_prompt_leak" (пишет scanner-sysleak).
export interface SysLeakTrialResult {
  id: number;
  payload_name: string | null;
  payload_family: string | null;
  verdict: InjectionVerdict;
  verdict_reason: string | null;
  response_excerpt: string;
}

export interface SysLeakPayloadGroup {
  payload_name: string;
  payload_family: string | null;
  trials: number;
  vulnerable: number;
  robust: number;
  inconclusive: number;
  error: number;
  leak_rate: number;
}

export interface SystemPromptLeakResults {
  engine: string;
  summary: {
    trials: number;
    leaked: number;
    robust: number;
    inconclusive: number;
    error: number;
    leak_rate: number;
  };
  by_payload: SysLeakPayloadGroup[];
  trials: SysLeakTrialResult[];
  error?: string;
}

// --- единый отчёт сканирования (GET /scans/{id}/report) ---------------------
// Один формат для всех сканеров: одинаковые метрики и одинаковые находки.
// Нормализацию делает control-api (app/reports.py).

export type ScanRating = "protected" | "partial" | "unsafe" | "unknown";
export type AnalysisKind = "dynamic" | "static" | "mixed";
export type FindingSeverity = "critical" | "high" | "medium" | "low" | "info";

export interface ReportFindingLocation {
  file: string | null;
  start_line: number | null;
  end_line: number | null;
}

export interface ReportConversationTurn {
  role: string;
  content: string;
  injected?: boolean;
  note?: string;
  name?: string | null;
}

export interface ReportFinding {
  id: string;
  title: string;
  severity: FindingSeverity;
  category: string;
  rule_id: string | null;
  description: string;
  recommendation: string;
  location: ReportFindingLocation | null;
  evidence: { detail?: string; conversation?: ReportConversationTurn[]; engine?: string; target?: string; trial_id?: number } | null;
}

export interface ReportMetrics {
  analysis: AnalysisKind;
  checks_total: number | null;
  checks_passed: number | null;
  checks_failed: number | null;
  checks_errored: number | null;
  checks_skipped: number | null;
  resistance_rate: number | null;
  attack_success_rate: number | null;
  findings_total: number;
  by_severity: Record<FindingSeverity, number>;
}

export interface ScanReport {
  version: number;
  scan: {
    id: number;
    name: string;
    type: ScanType;
    type_label: string;
    status: ScanStatus;
    analysis: AnalysisKind;
    asset_kind: AssetKind | null;
    asset_id: number | null;
    phase: string | null;
    error: string | null;
    created_at: string | null;
    started_at: string | null;
    finished_at: string | null;
  };
  metrics: ReportMetrics;
  rating: ScanRating;
  rating_label: string;
  findings: ReportFinding[];
  engine: { name: string | null; version: string | null; coverage: string | null; duration_sec: number | null };
}

// --- сводка актива (GET /assets/{kind}/{id}/summary) ------------------------

export interface AssetSummaryScanType {
  type: ScanType;
  type_label: string;
  analysis: AnalysisKind;
  scan_id: number;
  scan_name: string;
  finished_at: string | null;
  rating: ScanRating;
  rating_label: string;
  findings_total: number;
  resistance_rate: number | null;
  attack_success_rate: number | null;
  checks_total: number | null;
}

export interface AssetSummary {
  asset: { kind: AssetKind; id: number };
  scans: { total: number; pending: number; running: number; completed: number; failed: number };
  findings_total: number;
  by_severity: Record<FindingSeverity, number>;
  rating: ScanRating;
  rating_label: string;
  by_scan_type: AssetSummaryScanType[];
  last_scan_at: string | null;
}
