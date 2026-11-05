import { useLocation } from "react-router-dom";
import { navigation } from "../navigation";
import { useAuth } from "../auth/AuthContext";

const ROLE_BADGES: Record<string, string> = {
  admin: "Администратор",
  editor: "Редактор",
  reader: "Наблюдатель",
};

function getLabel(pathname: string): string {
  for (const item of navigation) {
    if (pathname === item.to || (!item.end && pathname.startsWith(`${item.to}/`))) return item.label;
  }
  return "Agent Scanner";
}

export function Header() {
  const { pathname } = useLocation();
  const label = getLabel(pathname);
  const {openMode, user, orgChoices, activeOrgId, setActiveOrgId, activeRole, logout} = useAuth();

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

      {!openMode && user != null && (
        <>
          {orgChoices.length > 0 && (
            <label style={{display: "inline-flex", alignItems: "center", gap: "0.6rem", margin: 0}}>
              <span style={{fontSize: "var(--font-caption-s-size)", color: "var(--text-500)"}}>Организация</span>
              <select
                value={activeOrgId ?? ""}
                onChange={(e) => setActiveOrgId(Number(e.target.value) || null)}
                style={{maxWidth: "22rem"}}
              >
                {orgChoices.map((org) => (
                  <option key={org.org_id} value={org.org_id}>{org.org_name}</option>
                ))}
              </select>
            </label>
          )}
          {orgChoices.length === 0 && (
            <span style={{color: "var(--text-500)", fontSize: "var(--font-caption-s-size)"}}>
              Нет организаций -- создайте её в разделе «Организации»
            </span>
          )}

          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.8rem",
              borderRadius: "999px",
              background: "var(--background-generic)",
              padding: "0.5rem 1.2rem",
              fontSize: "var(--font-caption-s-size)",
              color: "var(--text-700, var(--text-900))",
              fontWeight: 500,
            }}
            title={user.email ?? user.login}
          >
            <strong>{user.display_name ?? user.login}</strong>
            {user.is_superadmin
              ? <span className="badge">Системный администратор</span>
              : activeRole && <span className="badge">{ROLE_BADGES[activeRole]}</span>}
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => void logout()}
              style={{padding: "0.2rem 0.8rem"}}
            >
              Выйти
            </button>
          </span>
        </>
      )}

      {openMode && (
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
          title="SESSION_SECRET_KEY не задан -- эндпоинты открыты"
        >
          Авторизация выключена · dev
        </span>
      )}
    </header>
  );
}
