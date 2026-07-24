import type { ReactNode } from "react";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div style={{ marginBottom: "var(--space-6)" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: "var(--space-4)",
          marginBottom: description ? "0.6rem" : 0,
        }}
      >
        <h1
          style={{
            margin: 0,
            fontSize: "var(--font-header-m-size)",
            lineHeight: "var(--font-header-m-line)",
            fontWeight: 700,
            color: "var(--text-1000)",
            letterSpacing: "-0.02em",
          }}
        >
          {title}
        </h1>
        {actions && <div style={{ flexShrink: 0, paddingTop: "0.4rem" }}>{actions}</div>}
      </div>
      {description && (
        <p
          style={{
            margin: 0,
            fontSize: "var(--font-caption-m-size)",
            lineHeight: "var(--font-body-line)",
            color: "var(--text-500)",
            maxWidth: "72ch",
          }}
        >
          {description}
        </p>
      )}
      <div
        style={{
          marginTop: "2.4rem",
          borderTop: "0.1rem solid var(--separator-list)",
        }}
      />
    </div>
  );
}
