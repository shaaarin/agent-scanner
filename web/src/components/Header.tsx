import { useLocation } from "react-router-dom";

const SECTION_LABELS: [string, string, boolean][] = [
  ["/campaigns", "Сканирования", false],
  ["/templates", "Шаблоны инъекций", false],
  ["/llm-models", "LLM-модели", false],
  ["/agent-configs", "Конфигурации агентов", false],
  ["/events", "События", false],
  ["/findings", "Уязвимости", false],
  ["/", "Главная", true],
];

function getLabel(pathname: string): string {
  for (const [path, label, exact] of SECTION_LABELS) {
    if (exact ? pathname === path : pathname.startsWith(path)) return label;
  }
  return "Agent Scanner";
}

export function Header() {
  const { pathname } = useLocation();
  const label = getLabel(pathname);

  return (
    <header
      style={{
        gridArea: "header",
        display: "flex",
        alignItems: "center",
        height: "var(--header-height)",
        padding: "0 3.2rem",
        background: "var(--background-base)",
        borderBottom: "0.1rem solid var(--separator-default)",
        zIndex: 20,
        gap: "1.6rem",
      }}
    >
      <span
        style={{
          flex: 1,
          fontWeight: 600,
          fontSize: "var(--font-body-size)",
          color: "var(--text-900)",
          letterSpacing: "-0.01em",
        }}
      >
        {label}
      </span>

      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          borderRadius: "999px",
          background: "var(--background-generic)",
          padding: "0.5rem 1.2rem",
          fontSize: "var(--font-caption-s-size)",
          color: "var(--text-500)",
          fontWeight: 500,
          letterSpacing: "0.01em",
        }}
      >
        Agent Scanner · локально
      </span>
    </header>
  );
}
