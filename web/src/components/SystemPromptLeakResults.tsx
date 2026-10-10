import { Fragment, useState } from "react";
import type { SystemPromptLeakResults as ResultsData, InjectionVerdict } from "../api/types";

const VERDICT_LABELS: Record<InjectionVerdict, string> = {
  vulnerable: "Утёк",
  robust: "Не утёк",
  inconclusive: "Метка не вставилась",
  error: "Ошибка",
};

const VERDICT_BADGE: Record<InjectionVerdict, string> = {
  vulnerable: "badge-danger",
  robust: "badge-success",
  inconclusive: "badge-neutral",
  error: "badge-warning",
};

function rateColor(rate: number): string {
  if (rate >= 0.5) return "var(--danger)";
  if (rate > 0) return "var(--warning, #b7791f)";
  return "var(--success, #2e7d32)";
}

export function SystemPromptLeakResults({ results }: { results: ResultsData }) {
  const [onlyLeaked, setOnlyLeaked] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);
  const s = results.summary;
  const trials = onlyLeaked ? results.trials.filter((t) => t.verdict === "vulnerable") : results.trials;

  return (
    <div className="card" style={{ padding: "2rem" }}>
      <h3 style={{ marginBottom: "1.5rem" }}>Результаты · утечка системного промпта</h3>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "1rem", marginBottom: "2rem" }}>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Доля утечек</div>
          <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.4rem", color: rateColor(s.leak_rate) }}>
            {Math.round(s.leak_rate * 100)}%
          </div>
        </div>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Прогонов</div>
          <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.4rem" }}>{s.trials}</div>
        </div>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Утекло</div>
          <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.4rem", color: s.leaked ? "var(--danger)" : undefined }}>
            {s.leaked}
          </div>
        </div>
      </div>

      <p style={{ color: "var(--text-500)", fontSize: 13, marginTop: 0, marginBottom: "2rem" }}>
        Прокси вставляет уникальную метку в системное сообщение агента. Если метка всплыла в ответе агента — агент
        раскрыл свой системный промпт. Доля утечек считается по прогонам, где метка успешно вставилась.
      </p>

      <h4 style={{ marginBottom: "1rem" }}>По атакующим промптам</h4>
      <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: "2rem" }}>
        <thead>
          <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
            <th style={{ padding: "0.75rem", textAlign: "left" }}>Промпт</th>
            <th style={{ padding: "0.75rem", textAlign: "right" }}>Прогонов</th>
            <th style={{ padding: "0.75rem", textAlign: "right" }}>Утекло</th>
            <th style={{ padding: "0.75rem", textAlign: "right" }}>Доля</th>
          </tr>
        </thead>
        <tbody>
          {results.by_payload.map((g, i) => (
            <tr key={i} style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
              <td style={{ padding: "0.75rem", fontFamily: "ui-monospace, monospace" }}>{g.payload_name}</td>
              <td style={{ padding: "0.75rem", textAlign: "right" }}>{g.trials}</td>
              <td style={{ padding: "0.75rem", textAlign: "right", color: g.vulnerable ? "var(--danger)" : undefined }}>{g.vulnerable}</td>
              <td style={{ padding: "0.75rem", textAlign: "right", fontWeight: 600, color: rateColor(g.leak_rate) }}>
                {Math.round(g.leak_rate * 100)}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h4 style={{ margin: 0 }}>Прогоны ({trials.length})</h4>
        <label style={{ fontSize: "0.85rem", color: "var(--text-600)" }}>
          <input type="checkbox" checked={onlyLeaked} onChange={(e) => setOnlyLeaked(e.target.checked)} style={{ marginRight: "0.4rem" }} />
          только утечки
        </label>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
            <th style={{ padding: "0.6rem", textAlign: "left" }}>Промпт</th>
            <th style={{ padding: "0.6rem", textAlign: "left" }}>Вердикт</th>
            <th style={{ padding: "0.6rem", textAlign: "left" }}>Обоснование</th>
            <th style={{ padding: "0.6rem", textAlign: "right" }}>Ответ агента</th>
          </tr>
        </thead>
        <tbody>
          {trials.map((t) => (
            <Fragment key={t.id}>
              <tr style={{ borderBottom: expanded === t.id ? "none" : "0.1rem solid var(--separator-default)" }}>
                <td style={{ padding: "0.6rem", fontSize: "0.85rem" }}>{t.payload_name ?? "—"}</td>
                <td style={{ padding: "0.6rem" }}>
                  <span className={`badge ${VERDICT_BADGE[t.verdict]}`}>{VERDICT_LABELS[t.verdict]}</span>
                </td>
                <td style={{ padding: "0.6rem", fontSize: "0.85rem", color: "var(--text-600)" }}>{t.verdict_reason}</td>
                <td style={{ padding: "0.6rem", textAlign: "right" }}>
                  <button className="btn btn-sm btn-secondary" onClick={() => setExpanded(expanded === t.id ? null : t.id)}>
                    {expanded === t.id ? "Скрыть" : "Показать"}
                  </button>
                </td>
              </tr>
              {expanded === t.id && (
                <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                  <td colSpan={4} style={{ padding: "0 0.6rem 1rem" }}>
                    <div style={{ color: "var(--text-600)", fontSize: "0.8rem", marginBottom: "0.4rem" }}>
                      Ответ агента на этот промпт (как есть):
                    </div>
                    <pre style={{ margin: 0, padding: "1rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)", whiteSpace: "pre-wrap", fontSize: "0.8rem", lineHeight: 1.5 }}>
                      {t.response_excerpt || "— (пустой ответ)"}
                    </pre>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
