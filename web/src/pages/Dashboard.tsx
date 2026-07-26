import { Link } from "react-router-dom";
import { PageHeader } from "../components/PageHeader";
import { Icon, type IconName } from "../components/Icon";

const tiles: { to: string; label: string; description: string; icon: IconName }[] = [
  {
    to: "/campaigns",
    label: "Сканирования",
    description: "Настройка и запуск сканирований тестируемого агента.",
    icon: "scans",
  },
  {
    to: "/attack-prompts",
    label: "Атаки",
    description: "Библиотека техник атак: prompt-инъекции, джейлбрейки и другие.",
    icon: "attacks",
  },
  {
    to: "/llm-models",
    label: "LLM-модели",
    description: "Подключения к LLM-провайдерам, используемые в сканированиях.",
    icon: "llm",
  },
  {
    to: "/agent-configs",
    label: "Конфигурации агентов",
    description: "Параметры запуска и взаимодействия с тестируемым агентом.",
    icon: "agent",
  },
  {
    to: "/events",
    label: "События",
    description: "Трафик, перехваченный прокси, в реальном времени.",
    icon: "events",
  },
  {
    to: "/findings",
    label: "Уязвимости",
    description: "Обмены, в которых инъекция прошла успешно.",
    icon: "findings",
  },
];

export function Dashboard() {
  return (
    <div>
      <PageHeader
        title="Agent Scanner"
        description="Платформа для тестирования LLM-агентов на уязвимости к prompt-инъекциям и атакам через вызов инструментов."
      />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
          gap: "2.4rem",
        }}
      >
        {tiles.map((tile) => (
          <Link
            key={tile.to}
            to={tile.to}
            className="card dashboard-tile"
            style={{
              display: "flex",
              flexDirection: "column",
              color: "inherit",
              textDecoration: "none",
            }}
          >
            <div
              style={{
                width: "4.4rem",
                height: "4.4rem",
                borderRadius: "var(--radius-m)",
                background: "var(--brand-150)",
                color: "var(--brand)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                marginBottom: "1.6rem",
                flexShrink: 0,
              }}
            >
              <Icon name={tile.icon} size={22} />
            </div>
            <h3
              style={{
                marginBottom: "0.4rem",
                fontSize: "var(--font-body-size)",
                fontWeight: 600,
                color: "var(--text-900)",
              }}
            >
              {tile.label}
            </h3>
            <p
              style={{
                marginBottom: 0,
                fontSize: "var(--font-caption-m-size)",
                color: "var(--text-400)",
                lineHeight: "var(--font-caption-m-line)",
              }}
            >
              {tile.description}
            </p>
          </Link>
        ))}
      </div>
    </div>
  );
}
