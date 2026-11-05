import type { IconName } from "./components/Icon";

// Shared by the sidebar, dashboard and current-section heading.
export const navigation: {to: string; label: string; icon: IconName; description: string; end?: boolean}[] = [
  {to: "/", label: "Главная", icon: "home", description: "Разделы платформы.", end: true},
  {to: "/assets", label: "Активы", icon: "agent", description: "Агенты, MCP-серверы и skills: добавляйте активы и запускайте для них проверки."},
  {to: "/scans", label: "Сканирования", icon: "scans", description: "Все запуски проверок: динамическое тестирование, анализ кода, MCP и инъекции."},
  {to: "/llm-models", label: "LLM-модели", icon: "llm", description: "Провайдеры и модели, которые оценивают ответы агента и порождают атаки."},
  {to: "/orgs", label: "Организации", icon: "org", description: "Организации-владельцы активов: участники и их роли (администратор, редактор, наблюдатель)."},
  {to: "/library", label: "Библиотека знаний", icon: "library", description: "Материалы по безопасности ИИ: агенты, MCP, навыки и модели."},
  {to: "/help", label: "Справка", icon: "help", description: "Как подготовить MCP-актив, выбрать движки, запустить скан и прочитать результаты."},
  {to: "/events", label: "События", icon: "events", description: "Запросы и ответы агента, перехваченные прокси, в реальном времени."},
];
