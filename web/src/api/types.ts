export type InjectionTarget = "user_message" | "tool_result" | "assistant_response" | "system_prompt";
export type InjectionMode = "append" | "prepend" | "replace";
export type SuccessIndicatorField = "tool_name" | "tool_arguments" | "response_text";
export type CampaignStatus = "new" | "active" | "paused" | "cancelled";
export type ProviderType = "openai" | "anthropic";
export type InteractionMode = "none" | "api" | "langgraph";
export type InteractorPersona = "attacker" | "benign_user";
export type FuzzMode = "adaptive" | "non_adaptive";
export type FuzzRunStatus = "pending" | "running" | "paused" | "stopped" | "completed";

export interface InjectionTemplate {
  id: number;
  name: string;
  description: string;
  target: InjectionTarget;
  mode: InjectionMode;
  payload: string;
  success_indicator: string | null;
  success_indicator_field: SuccessIndicatorField;
  tags: string[];
  created_at: string;
}

export interface AttackPrompt {
  id: number;
  name: string;
  description: string;
  system_prompt: string;
  tags: string[];
  created_at: string;
}

export interface Campaign {
  id: number;
  name: string;
  session_id: string;
  status: CampaignStatus;
  agent_config_id: number | null;
  interactor_llm_model_id: number | null;
  generator_llm_model_id: number | null;
  interactor_persona: InteractorPersona | null;
  user_instruction: string | null;
  agent_namespace: string | null;
  agent_pod_name: string | null;
  build_job_name: string | null;
  built_image: string | null;
  created_at: string;
  updated_at: string;
}

export interface TrafficEvent {
  id: number;
  session_id: string;
  campaign_id: number | null;
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

export interface InteractorTurn {
  speaker: "interactor" | "agent";
  text: string;
}

export interface InteractorRun {
  transcript: InteractorTurn[];
  turns: number;
  success_detected: boolean;
}

export interface FuzzRun {
  id: number;
  name: string;
  base_campaign_id: number;
  injection_target: InjectionTarget;
  mode: FuzzMode;
  seed_template_ids: number[];
  attack_prompt_ids: number[];
  judge_llm_model_id: number | null;
  max_iterations: number;
  stop_on_success: boolean;
  status: FuzzRunStatus;
  success_attempt_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface FuzzAttempt {
  id: number;
  fuzz_run_id: number;
  iteration: number;
  seed_template_id: number;
  template_id: number;
  mutation_strategy: string;
  detector_success: boolean;
  judge_score: number;
  judge_verdict: string;
  reward: number;
  success: boolean;
  created_at: string;
}

export interface TreeRun {
  id: number;
  name: string;
  base_campaign_id: number;
  seed_template_ids: number[];
  attack_prompt_ids: number[];
  judge_llm_model_id: number | null;
  max_checkpoints: number | null;
  attempts_per_checkpoint: number;
  mode: FuzzMode;
  status: FuzzRunStatus;
  created_at: string;
  updated_at: string;
}

export interface ConversationNode {
  id: number;
  tree_run_id: number;
  turn_index: number;
  message_sent: string;
  agent_reply: string;
  created_at: string;
}

export interface InjectionProbeTrajectoryTurn {
  // Always length 1: one direct chat-completion call against the
  // checkpoint's mutated message array -- no re-driven multi-turn agent
  // conversation anymore. Both are the raw OpenAI-shaped JSON bodies.
  request: Record<string, unknown>;
  response: Record<string, unknown>;
}

export interface InjectionProbe {
  id: number;
  tree_run_id: number;
  checkpoint_occurrence: number;
  attempt_index: number;
  seed_template_id: number;
  template_id: number;
  tool_name: string;
  original_tool_result: string;
  injected_tool_result: string;
  trajectory: InjectionProbeTrajectoryTurn[];
  stopped_reason: string;
  detector_success: boolean;
  judge_score: number;
  judge_verdict: string;
  reward: number;
  success: boolean;
  diverged_from_backbone: boolean;
  divergence_detail: string;
  created_at: string;
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
