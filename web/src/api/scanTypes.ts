import type { CodeScanSeverity, Scan, ScanType } from "./types";

export const TERMINAL_SCAN_STATUSES = ["completed", "success", "partially_failed", "failed"];

// Historical MCP reports retain their stored status. Render their known
// summary consistently with new scans without rewriting history in the DB.
export function displayedScanStatus(scan: Pick<Scan, "type" | "status" | "results">): string {
  if (scan.type === "mcp" && scan.status === "completed" && scan.results) {
    try {
      const summary = JSON.parse(scan.results)?.summary;
      if (summary && typeof summary.completed === "number" && typeof summary.failed === "number") {
        if (!summary.completed) return "failed";
        return summary.failed || summary.pending ? "partially_failed" : "success";
      }
    } catch { /* Legacy report: keep its original status. */ }
  }
  return scan.status;
}

export const SCAN_TYPE_LABELS: Record<ScanType, string> = {
  deep_team: "[динамическое тестирование] DeepTeam",
  pyrit_scan: "[динамическое тестирование] PyRIT",
  code_scan: "[статический анализ] Promptfoo",
  ai_code_scan: "[статический анализ] Semgrep (AI-код)",
  indirect_injection: "[динамическое тестирование] Косвенные инъекции",
  system_prompt_leak: "[динамическое тестирование] Утечка системного промпта",
  mcp: "[статический и динамический анализ] MCP",
  agent_skills: "[статический анализ] Agent Skills",
};

export function scanTypeLabel(type: string): string {
  return SCAN_TYPE_LABELS[type as ScanType] ?? type;
}

// Лейблы типов сканов и фазы приходят из реестра сканеров (GET /scanners);
// здесь -- только fallback, пока реестр не ответил или сканер недоступен.

export const SEVERITY_ORDER: CodeScanSeverity[] = ["critical", "high", "medium", "low"];

export const SEVERITY_LABELS: Record<CodeScanSeverity, string> = {
  critical: "Критическая",
  high: "Высокая",
  medium: "Средняя",
  low: "Низкая",
};

export const SEVERITY_BADGES: Record<CodeScanSeverity, string> = {
  critical: "badge-danger",
  high: "badge-danger",
  medium: "badge-warning",
  low: "badge-neutral",
};
