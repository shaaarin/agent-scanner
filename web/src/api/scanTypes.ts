import type { CodeScanSeverity, ScanType } from "./types";

export const SCAN_TYPE_LABELS: Record<ScanType, string> = {
  deep_team: "Динамическое тестирование",
  code_scan: "Анализ кода",
  indirect_injection: "Косвенные инъекции",
  system_prompt_leak: "Утечка системного промпта",
  mcp: "MCP",
  agent_skills: "Agent Skills",
};

export function scanTypeLabel(type: string): string {
  return SCAN_TYPE_LABELS[type as ScanType] ?? type;
}

// Фазы, которые пишет сканер каждого типа (Scan.phase), в порядке прохождения.
export const SCAN_PHASES: Partial<Record<ScanType, string[]>> = {
  deep_team: [
    "Инициализация",
    "Запуск агента",
    "Ожидание агента",
    "Тестирование",
    "Сохранение результатов",
    "Завершено",
  ],
  code_scan: [
    "Инициализация",
    "Клонирование",
    "Анализ кода",
    "Сохранение результатов",
    "Завершено",
  ],
  indirect_injection: [
    "Инициализация",
    "Запуск агента",
    "Ожидание агента",
    "Базовый прогон",
    "Фаззинг",
    "Сохранение результатов",
    "Завершено",
  ],
  system_prompt_leak: [
    "Инициализация",
    "Запуск агента",
    "Ожидание агента",
    "Тестирование",
    "Сохранение результатов",
    "Завершено",
  ],
};

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
