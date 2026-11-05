import { useState } from "react";
import type { PyritResults as ResultsData, PyritAttackRow } from "../api/types";

const OUTCOME_LABELS: Record<PyritAttackRow["outcome"], string> = {
  success: "Цель достигнута",
  failure: "Отражено",
  error: "Ошибка",
  undetermined: "Не определено",
};

const OUTCOME_BADGE: Record<PyritAttackRow["outcome"], string> = {
  success: "badge-danger",
  failure: "badge-success",
  error: "badge-warning",
  undetermined: "badge-neutral",
};

const TECHNIQUE_LABELS: Record<string, string> = {
  plain: "Без изменений (plain)",
  base64: "Base64",
  rot13: "ROT13",
  leetspeak: "Leetspeak",
  charswap: "Подмена символов",
  morse: "Азбука Морзе",
  zero_width: "Zero-width символы",
  skeleton_key: "Skeleton Key",
  crescendo: "Crescendo (мульти-оборотная)",
  pair: "PAIR (мульти-оборотная)",
  red_team: "Red Teaming (мульти-оборотная)",
};

function asrColor(asr: number): string {
  if (asr >= 0.5) return "var(--danger)";
  if (asr > 0) return "var(--warning, #b7791f)";
  return "var(--success, #2e7d32)";
}

export function PyritResults({ results }: { results: ResultsData }) {
  const [onlySuccess, setOnlySuccess] = useState(false);
  const s = results.summary;
  const rows = onlySuccess ? results.attacks.filter((a) => a.outcome === "success") : results.attacks;

  return (
    <div className="card" style={{ padding: "2rem" }}>
      <h3 style={{ marginBottom: "1.5rem" }}>Результаты · PyRIT</h3>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "1rem", marginBottom: "2rem" }}>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>ASR (доля успешных атак)</div>
          <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.4rem", color: asrColor(s.asr) }}>
            {Math.round(s.asr * 100)}%
          </div>
        </div>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Прогонов</div>
          <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.4rem" }}>{s.runs}</div>
        </div>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Цель достигнута</div>
          <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.4rem", color: s.success ? "var(--danger)" : undefined }}>{s.success}</div>
        </div>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Отражено</div>
          <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.4rem" }}>{s.failure}</div>
        </div>
      </div>

      <p style={{ color: "var(--text-500)", fontSize: 13, marginTop: 0, marginBottom: "2rem" }}>
        «Цель достигнута» — модель-судья посчитала, что агент выполнил вредоносный запрос; ASR считается по прогонам
        с определённым исходом (успех + отражено).
        {results.engine_version ? ` Движок: PyRIT ${results.engine_version}.` : ""}
      </p>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h4 style={{ margin: 0 }}>Прогоны ({rows.length})</h4>
        <label style={{ fontSize: "0.85rem", color: "var(--text-600)" }}>
          <input type="checkbox" checked={onlySuccess} onChange={(e) => setOnlySuccess(e.target.checked)} style={{ marginRight: "0.4rem" }} />
          только успешные атаки
        </label>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
            <th style={{ padding: "0.6rem", textAlign: "left" }}>Техника</th>
            <th style={{ padding: "0.6rem", textAlign: "left" }}>Цель атаки</th>
            <th style={{ padding: "0.6rem", textAlign: "left" }}>Исход</th>
            <th style={{ padding: "0.6rem", textAlign: "left" }}>Ответ агента</th>
            <th style={{ padding: "0.6rem", textAlign: "left" }}>Обоснование судьи</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
              <td style={{ padding: "0.6rem", fontSize: "0.85rem" }}>{TECHNIQUE_LABELS[row.technique] ?? row.technique}</td>
              <td style={{ padding: "0.6rem", fontSize: "0.85rem", maxWidth: "18rem", whiteSpace: "pre-wrap" }}>{row.objective}</td>
              <td style={{ padding: "0.6rem" }}>
                <span className={`badge ${OUTCOME_BADGE[row.outcome]}`}>{OUTCOME_LABELS[row.outcome]}</span>
              </td>
              <td style={{ padding: "0.6rem", fontSize: "0.85rem", whiteSpace: "pre-wrap", maxWidth: "20rem" }}>{row.response || "—"}</td>
              <td style={{ padding: "0.6rem", fontSize: "0.85rem", color: "var(--text-600)" }}>{row.rationale || row.outcome_reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
