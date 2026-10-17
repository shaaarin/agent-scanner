import { useLocation } from "react-router-dom";
import { navigation } from "../navigation";

function getLabel(pathname: string): string {
  for (const item of navigation) {
    if (pathname === item.to || (!item.end && pathname.startsWith(`${item.to}/`))) return item.label;
  }
  return "Agent Scanner";
}

export function Header() {
  const { pathname } = useLocation();
  const label = getLabel(pathname);

  return (
    <header
      className="app-header"
      style={{
        gridArea: "header",
        display: "flex",
        alignItems: "center",
        height: "var(--header-height)",
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
        className="app-environment"
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
