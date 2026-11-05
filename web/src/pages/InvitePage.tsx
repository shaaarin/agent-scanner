import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { InviteInfo, OrgRole } from "../api/types";
import { useAuth } from "../auth/AuthContext";

const ROLE_LABELS: Record<OrgRole, string> = {
  admin: "Администратор",
  editor: "Редактор",
  reader: "Наблюдатель",
};

// Страница приглашения (/invite/<token>): показывает, куда зовут, и по кнопке
// присоединяет к организации. До входа весь интерфейс закрыт экраном входа --
// после входа пользователь возвращается на этот же URL и видит кнопку.
export function InvitePage() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const { refresh, setActiveOrgId } = useAuth();
  const [info, setInfo] = useState<InviteInfo | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "invalid" | "accepting">("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get<InviteInfo>(`/invites/${token}`)
      .then((data) => {
        setInfo(data);
        setStatus("ready");
      })
      .catch(() => setStatus("invalid"));
  }, [token]);

  const accept = async () => {
    setError("");
    setStatus("accepting");
    try {
      const joined = await api.post<{org_id: number}>(`/invites/${token}/accept`, {});
      await refresh();
      setActiveOrgId(joined.org_id);
      navigate("/assets");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus("ready");
    }
  };

  return (
    <div
      style={{
        minHeight: "100dvh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--background-warm)",
        padding: "2rem",
      }}
    >
      <div
        style={{
          width: "min(42rem, 100%)",
          background: "var(--background-base)",
          border: "0.1rem solid var(--separator-default)",
          borderRadius: "var(--radius-l, 1.2rem)",
          padding: "3.2rem",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: "1.2rem",
          textAlign: "center",
        }}
      >
        <span
          style={{
            width: "5.2rem",
            height: "5.2rem",
            borderRadius: "var(--radius-m)",
            background: "#fff",
            border: "0.1rem solid var(--separator-default)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "0.6rem",
          }}
        >
          <img src="/emblem.svg" alt="Agent Scanner" style={{width: "100%", height: "100%", objectFit: "contain"}} />
        </span>

        {status === "loading" && <p style={{color: "var(--text-500)"}}>Загрузка приглашения…</p>}

        {status === "invalid" && (
          <>
            <h1 style={{margin: 0, fontSize: "2rem"}}>Приглашение недействительно</h1>
            <p style={{margin: 0, color: "var(--text-500)"}}>
              Ссылка не найдена или уже использована. Попросите администратора организации
              создать новую.
            </p>
            <button className="btn btn-secondary" onClick={() => navigate("/")}>На главную</button>
          </>
        )}

        {(status === "ready" || status === "accepting") && info && (
          <>
            <h1 style={{margin: 0, fontSize: "2rem"}}>Приглашение в организацию</h1>
            <p style={{margin: 0, fontSize: "1.6rem"}}>
              <strong>{info.org_name}</strong>
            </p>
            <p style={{margin: 0, color: "var(--text-500)"}}>
              Роль в организации: <strong>{ROLE_LABELS[info.role]}</strong>
            </p>
            {!info.valid ? (
              <>
                <p role="alert" style={{margin: 0, color: "var(--danger, #b42318)"}}>
                  Эта ссылка уже использована.
                </p>
                <button className="btn btn-secondary" onClick={() => navigate("/")}>На главную</button>
              </>
            ) : (
              <>
                {error && <p role="alert" style={{margin: 0, color: "var(--danger, #b42318)"}}>{error}</p>}
                <button
                  className="btn btn-primary"
                  onClick={() => void accept()}
                  disabled={status === "accepting"}
                  style={{fontSize: "1.6rem", padding: "1.2rem 2.4rem"}}
                >
                  {status === "accepting" ? "Присоединяем…" : "Принять приглашение"}
                </button>
                <p style={{margin: 0, color: "var(--text-500)", fontSize: "1.25rem"}}>
                  Активы, модели и сканирования этой организации появятся в вашем дашборде.
                </p>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
