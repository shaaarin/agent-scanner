import { NavLink } from "react-router-dom";
import { Icon, type IconName } from "./Icon";

const items: { to: string; label: string; icon: IconName; end?: boolean }[] = [
  { to: "/", label: "Главная", icon: "home", end: true },
  { to: "/scans", label: "Сканирования", icon: "scans" },
  { to: "/llm-models", label: "LLM-модели", icon: "llm" },
  { to: "/agent-configs", label: "Конфигурации агентов", icon: "agent" },
  { to: "/library", label: "Библиотека знаний", icon: "library" },
  { to: "/events", label: "События", icon: "events" },
];

export function Sidebar() {
  return (
    <aside
      style={{
        gridArea: "sidebar",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        width: "var(--sidebar-width)",
        height: "100dvh",
        position: "sticky",
        top: 0,
        background: "var(--background-base)",
        borderRight: "0.1rem solid var(--separator-default)",
        zIndex: 10,
      }}
    >
      <NavLink
        to="/"
        title="Agent Scanner"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          width: "100%",
          height: "var(--header-height)",
          borderBottom: "0.1rem solid var(--separator-default)",
          textDecoration: "none",
          flexShrink: 0,
        }}
      >
        <span
          style={{
            width: "3.6rem",
            height: "3.6rem",
            borderRadius: "var(--radius-m)",
            background: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            overflow: "hidden",
            padding: "0.4rem",
          }}
        >
          <img
            src="https://cabinet.miem.hse.ru/miem-logo-square.svg"
            alt="MIEM"
            style={{ width: "100%", height: "100%", objectFit: "contain" }}
          />
        </span>
      </NavLink>

      <nav
        style={{
          display: "flex",
          flexDirection: "column",
          width: "100%",
          gap: "0.2rem",
          padding: "1.2rem 0.8rem",
          flex: 1,
        }}
      >
        {items.map((item) => (
          <div key={item.to} className="sidebar-item" style={{ position: "relative" }}>
            <NavLink
              to={item.to}
              end={item.end}
              aria-label={item.label}
              title={item.label}
              className={({ isActive }) =>
                `sidebar-nav-link${isActive ? " is-active" : ""}`
              }
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                borderRadius: "var(--radius-m)",
                padding: "1rem",
                width: "100%",
                aspectRatio: "1",
                textDecoration: "none",
              }}
            >
              <Icon name={item.icon} size={20} />
            </NavLink>
            <div className="sidebar-flyout" role="tooltip">
              {item.label}
            </div>
          </div>
        ))}
      </nav>

      <style>{`
        .sidebar-nav-link {
          color: var(--text-500);
          transition: background 0.15s ease, color 0.15s ease;
        }
        .sidebar-nav-link:hover {
          background: var(--background-generic);
          color: var(--text-900);
        }
        .sidebar-nav-link.is-active {
          background: var(--brand);
          color: var(--brand-contrast);
        }
        .sidebar-nav-link.is-active:hover {
          background: var(--brand-hover);
        }
        .sidebar-flyout {
          position: absolute;
          top: 50%;
          left: calc(100% + 0.8rem);
          transform: translateY(-50%) translateX(-0.6rem);
          opacity: 0;
          pointer-events: none;
          transition: opacity 0.15s ease, transform 0.15s ease;
          z-index: 30;
          border-radius: var(--radius-m);
          background: var(--text-900);
          color: rgba(255, 255, 255, 0.92);
          padding: 0.5rem 1.1rem;
          white-space: nowrap;
          font-size: var(--font-caption-s-size);
          font-weight: 500;
          line-height: var(--font-caption-s-line);
          box-shadow: 0 0.4rem 1.6rem 0 var(--shadow-2);
        }
        .sidebar-item:hover .sidebar-flyout {
          opacity: 1;
          pointer-events: auto;
          transform: translateY(-50%) translateX(0);
        }
      `}</style>
    </aside>
  );
}
