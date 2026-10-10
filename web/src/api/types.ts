export type ProviderType = "openai" | "anthropic";
export type InteractionMode = "none" | "api" | "langgraph";

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
  git_repo_url: string;
  git_ref: string;
  git_access_token: string | null;
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

export type ScanType = "deep_team" | "code_scan" | "indirect_injection" | "system_prompt_leak" | "mcp" | "agent_skills";
export type ScanStatus = "pending" | "running" | "completed" | "failed";

export interface Scan {
  id: number;
  name: string;
  type: ScanType;
  agent_config_id: number;
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

export interface ScanConfig {
  // deep_team
  eval_llm_model_id?: number;
  vulnerabilities?: string[];
  attacks?: string[];
  frameworks?: string[];
  // code_scan
  min_severity?: CodeScanSeverity;
  guidance?: string | null;
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

// Scan.results для type = "code_scan" (пишет scanner-promptfoo).
export interface CodeScanResults {
  engine: string;
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
