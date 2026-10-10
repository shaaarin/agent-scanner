import { useState } from "react";
import type {
  IndirectInjectionResults as ResultsData,
  InjectionGroup,
  InjectionVerdict,
} from "../api/types";

const VERDICT_LABELS: Record<InjectionVerdict, string> = {
  vulnerable: "Уязвим",
  robust: "Устойчив",
  inconclusive: "Нет вызова",
  error: "Ошибка",
};

const VERDICT_BADGE: Record<InjectionVerdict, string> = {
  vulnerable: "badge-danger",
  robust: "badge-success",
  inconclusive: "badge-neutral",
  error: "badge-warning",
};

function asrColor(asr: number): string {
  if (asr >= 0.5) return "var(--danger)";
  if (asr > 0) return "var(--warning, #b7791f)";
  return "var(--success, #2e7d32)";
}

function GroupTable({ title, keyLabel, groups }: { title: string; keyLabel: string; groups: InjectionGroup[] }) {
  if (!groups.length) return null;
  return (
    <div style={{ marginBottom: "2rem" }}>
      <h4 style={{ marginBottom: "1rem" }}>{title}</h4>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
            <th style={{ padding: "0.75rem", textAlign: "left" }}>{keyLabel}</th>
            <th style={{ padding: "0.75rem", textAlign: "right" }}>Прогонов</th>
            <th style={{ padding: "0.75rem", textAlign: "right" }}>Уязвим</th>
            <th style={{ padding: "0.75rem", textAlign: "right" }}>Устойчив</th>
            <th style={{ padding: "0.75rem", textAlign: "right" }}>ASR</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g, i) => (
            <tr key={i} style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
              <td style={{ padding: "0.75rem", fontFamily: "ui-monospace, monospace" }}>
                {g.target_tool ?? g.payload_name ?? "—"}
              </td>
              <td style={{ padding: "0.75rem", textAlign: "right" }}>{g.trials}</td>
              <td style={{ padding: "0.75rem", textAlign: "right", color: g.vulnerable ? "var(--danger)" : undefined }}>
                {g.vulnerable}
              </td>
              <td style={{ padding: "0.75rem", textAlign: "right" }}>{g.robust}</td>
              <td style={{ padding: "0.75rem", textAlign: "right", fontWeight: 600, color: asrColor(g.asr) }}>
                {Math.round(g.asr * 100)}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function IndirectInjectionResults({ results }: { results: ResultsData }) {
  const [onlyVulnerable, setOnlyVulnerable] = useState(false);
  const s = results.summary;
  const trials = onlyVulnerable ? results.trials.filter((t) => t.verdict === "vulnerable") : results.trials;

  return (
    <div className="card" style={{ padding: "2rem" }}>
      <h3 style={{ marginBottom: "1.5rem" }}>Результаты · косвенные инъекции</h3>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "1rem", marginBottom: "2rem" }}>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>ASR (доля успешных атак)</div>
          <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.4rem", color: asrColor(s.asr) }}>
            {Math.round(s.asr * 100)}%
          </div>
        </div>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Прогонов</div>
          <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.4rem" }}>{s.trials}</div>
        </div>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Уязвимых</div>
          <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.4rem", color: s.vulnerable ? "var(--danger)" : undefined }}>
            {s.vulnerable}
          </div>
        </div>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Инъекция легла</div>
          <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.4rem" }}>{s.injected}</div>
        </div>
      </div>

      <p style={{ color: "var(--text-500)", fontSize: 13, marginTop: 0, marginBottom: "2rem" }}>
        ASR считается по прогонам, где инъекция реально легла в результат инструмента (уязвим + устойчив). «Нет вызова» —
        агент в этом прогоне не вызвал целевой инструмент, подложить было некуда.
      </p>

      <GroupTable title="По инструментам" keyLabel="Инструмент" groups={results.by_tool} />
      <GroupTable title="По payload'ам" keyLabel="Payload" groups={results.by_payload} />

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h4 style={{ margin: 0 }}>Прогоны ({trials.length})</h4>
        <label style={{ fontSize: "0.85rem", color: "var(--text-600)" }}>
          <input type="checkbox" checked={onlyVulnerable} onChange={(e) => setOnlyVulnerable(e.target.checked)} style={{ marginRight: "0.4rem" }} />
          только уязвимые
        </label>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
            <th style={{ padding: "0.6rem", textAlign: "left" }}>Инструмент</th>
            <th style={{ padding: "0.6rem", textAlign: "left" }}>Payload</th>
            <th style={{ padding: "0.6rem", textAlign: "left" }}>Вердикт</th>
            <th style={{ padding: "0.6rem", textAlign: "left" }}>Обоснование</th>
          </tr>
        </thead>
        <tbody>
          {trials.map((t) => (
            <tr key={t.id} style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
              <td style={{ padding: "0.6rem", fontFamily: "ui-monospace, monospace", fontSize: "0.85rem" }}>{t.target_tool ?? "—"}</td>
              <td style={{ padding: "0.6rem", fontSize: "0.85rem" }}>{t.payload_name ?? "—"}</td>
              <td style={{ padding: "0.6rem" }}>
                <span className={`badge ${VERDICT_BADGE[t.verdict]}`}>{VERDICT_LABELS[t.verdict]}</span>
              </td>
              <td style={{ padding: "0.6rem", fontSize: "0.85rem", color: "var(--text-600)" }}>{t.verdict_reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
