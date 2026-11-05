import { useState } from "react";
import { useAuth } from "../auth/AuthContext";

// Строгая политика пароля -- зеркалит app/auth/passwords.py (бекенд
// валидирует независимо и вернёт свой текст, если что-то изменится).
const MIN_PASSWORD_LEN = 10;

function passwordProblems(password: string): string[] {
  const problems: string[] = [];
  if (password.length < MIN_PASSWORD_LEN) problems.push(`минимум ${MIN_PASSWORD_LEN} символов`);
  if (!/[A-ZА-ЯЁ]/.test(password)) problems.push("заглавная буква");
  if (!/[a-zа-яё]/.test(password)) problems.push("строчная буква");
  if (!/[0-9]/.test(password)) problems.push("цифра");
  if (!/[^A-Za-zА-Яа-яЁё0-9]/.test(password)) problems.push("спецсимвол (например !@#$%)");
  return problems;
}

// Экран входа: логин + пароль. Регистрация открыта -- любой может создать
// учётку и свою организацию; в чужие организации попадают по приглашению.
export function LoginScreen() {
  const {login, register} = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [loginValue, setLoginValue] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (mode === "register") {
      const problems = passwordProblems(password);
      if (problems.length) {
        setError("Пароль не соответствует строгой политике. Требуется: " + problems.join(", "));
        return;
      }
    }
    setBusy(true);
    try {
      if (mode === "login") await login(loginValue, password);
      else await register(loginValue, password, displayName);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
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
          gap: "1.6rem",
        }}
      >
        <div style={{display: "flex", alignItems: "center", gap: "1.2rem"}}>
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
              flexShrink: 0,
            }}
          >
            <img src="/emblem.svg" alt="Agent Scanner" style={{width: "100%", height: "100%", objectFit: "contain"}} />
          </span>
          <div>
            <h1 style={{margin: 0, fontSize: "2.2rem", letterSpacing: "-0.02em"}}>Agent Scanner</h1>
            <p style={{margin: 0, color: "var(--text-500)"}}>Платформа проверки безопасности LLM-агентов</p>
          </div>
        </div>

        <div style={{display: "flex", gap: "0.5rem"}}>
          <button
            className={`btn ${mode === "login" ? "btn-primary" : "btn-secondary"}`}
            onClick={() => {setMode("login"); setError("");}}
          >
            Вход
          </button>
          <button
            className={`btn ${mode === "register" ? "btn-primary" : "btn-secondary"}`}
            onClick={() => {setMode("register"); setError("");}}
          >
            Регистрация
          </button>
        </div>

        <form onSubmit={submit} style={{display: "grid", gap: "1.2rem"}}>
          {mode === "register" && (
            <label>
              Имя
              <input
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="Как вас зовут (необязательно)"
                autoComplete="name"
              />
            </label>
          )}
          <label>
            Логин
            <input
              value={loginValue}
              onChange={(e) => setLoginValue(e.target.value)}
              placeholder="ivan"
              autoComplete={mode === "login" ? "username" : "off"}
              required
              autoFocus
            />
          </label>
          <label>
            Пароль
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={mode === "register" ? "Минимум 10 символов: A-z, цифры, спецсимвол" : ""}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
            />
          </label>
          {mode === "register" && (
            <p style={{margin: "-0.6rem 0 0", color: "var(--text-500)", fontSize: "1.25rem"}}>
              Строгая политика: минимум 10 символов, заглавные и строчные буквы, цифра и спецсимвол.
            </p>
          )}

          {error && (
            <p role="alert" style={{margin: 0, color: "var(--danger, #b42318)", fontWeight: 500}}>
              {error}
            </p>
          )}

          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? "Подождите…" : mode === "login" ? "Войти" : "Создать учётную запись"}
          </button>
        </form>

        <p style={{margin: 0, color: "var(--text-500)", fontSize: "1.3rem"}}>
          После входа можно создать свою организацию: активы, LLM-модели и сканирования
          хранятся внутри организаций. В чужую организацию попадают по приглашению её
          администратора.
        </p>
      </div>
    </div>
  );
}
