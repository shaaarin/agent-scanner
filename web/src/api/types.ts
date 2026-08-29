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
  injected: boolean;
  injection_target: string | null;
  success_detected: boolean;
  detail: string;
  raw_excerpt: string;
  upstream_base_url: string | null;
  request_authorization: string | null;
  created_at: string;
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
  interaction_mode: InteractionMode;
  api_config: Record<string, unknown> | null;
  langgraph_config: Record<string, unknown> | null;
  created_at: string;
}

export type ScanType = "deep_team" | "mcp" | "agent_skills";
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
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ScanConfig {
  eval_llm_model_id?: number;
  vulnerabilities?: string[];
  attacks?: string[];
  frameworks?: string[];
}

export interface ScanResults {
  vulnerability_results?: Array<{
    vulnerability: string;
    passed: boolean;
    score: number;
    reasoning: string;
  }>;
  overall_score?: number;
  error?: string;
}
