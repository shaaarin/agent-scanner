import { Link } from "react-router-dom";
import { PageHeader } from "../components/PageHeader";
import { Icon } from "../components/Icon";
import { navigation } from "../navigation";

export function Dashboard() {
  return (
    <div>
      <PageHeader
        title="Agent Scanner"
        description="Платформа для проверки LLM-агентов на устойчивость к prompt-инъекциям и злоупотреблению инструментами."
      />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(min(220px, 100%), 1fr))",
          gap: "2.4rem",
        }}
      >
        {navigation.filter((item) => !item.end).map((tile) => (
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
