import type { PromptfooRedteamResults as ResultsData, RedteamPluginRow } from "../api/types";

function failColor(rate: number): string {
  if (rate >= 0.5) return "var(--danger)";
  if (rate > 0) return "var(--warning, #b7791f)";
  return "var(--success, #2e7d32)";
}

function PluginTable({ rows }: { rows: RedteamPluginRow[] }) {
  if (!rows.length) return null;
  return (
    <table style={{ width: "100%", borderCollapse: "collapse" }}>
      <thead>
        <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
          <th style={{ padding: "0.6rem", textAlign: "left" }}>Плагин</th>
          <th style={{ padding: "0.6rem", textAlign: "right" }}>Тестов</th>
          <th style={{ padding: "0.6rem", textAlign: "right" }}>Атак прошло</th>
          <th style={{ padding: "0.6rem", textAlign: "right" }}>Доля прохождений</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const rate = row.tests ? row.failed / row.tests : 0;
          return (
            <tr key={row.plugin} style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
              <td style={{ padding: "0.6rem", fontFamily: "ui-monospace, monospace", fontSize: "0.85rem" }}>{row.plugin}</td>
              <td style={{ padding: "0.6rem", textAlign: "right" }}>{row.tests}</td>
              <td style={{ padding: "0.6rem", textAlign: "right", color: row.failed ? "var(--danger)" : undefined }}>{row.failed}</td>
              <td style={{ padding: "0.6rem", textAlign: "right", fontWeight: 600, color: failColor(rate) }}>{Math.round(rate * 100)}%</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function PromptfooRedteamResults({ results }: { results: ResultsData }) {
  const s = results.summary;
  return (
    <div className="card" style={{ padding: "2rem" }}>
      <h3 style={{ marginBottom: "1.5rem" }}>Результаты · Promptfoo red teaming</h3>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "1rem", marginBottom: "2rem" }}>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Доля прошедших атак</div>
          <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.4rem", color: failColor(s.fail_rate) }}>
            {Math.round(s.fail_rate * 100)}%
          </div>
        </div>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Атак прошло</div>
          <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.4rem", color: s.failed ? "var(--danger)" : undefined }}>{s.failed}</div>
        </div>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Агент устоял</div>
          <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.4rem" }}>{s.passed}</div>
        </div>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Всего тестов</div>
          <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.4rem" }}>{s.tests}</div>
        </div>
      </div>

      <p style={{ color: "var(--text-500)", fontSize: 13, marginTop: 0, marginBottom: "2rem" }}>
        Тест «провален», если агент выполнил вредоносный запрос, сгенерированный promptfoo.
        {results.purpose ? ` Назначение агента: «${results.purpose}».` : ""}
        {results.engine_version ? ` Движок: promptfoo ${results.engine_version}.` : ""}
      </p>

      <h4 style={{ marginBottom: "1rem" }}>По плагинам</h4>
      <div style={{ marginBottom: "2rem" }}>
        <PluginTable rows={results.plugins} />
      </div>

      {results.findings.length > 0 && (
        <>
          <h4 style={{ marginBottom: "1rem" }}>Прошедшие атаки ({results.findings.length})</h4>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                <th style={{ padding: "0.6rem", textAlign: "left" }}>Плагин</th>
                <th style={{ padding: "0.6rem", textAlign: "left" }}>Атака</th>
                <th style={{ padding: "0.6rem", textAlign: "left" }}>Ответ агента</th>
              </tr>
            </thead>
            <tbody>
              {results.findings.map((finding, index) => (
                <tr key={index} style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                  <td style={{ padding: "0.6rem", fontFamily: "ui-monospace, monospace", fontSize: "0.85rem" }}>{finding.plugin}</td>
                  <td style={{ padding: "0.6rem", fontSize: "0.85rem", whiteSpace: "pre-wrap", maxWidth: "20rem" }}>{finding.prompt || "—"}</td>
                  <td style={{ padding: "0.6rem", fontSize: "0.85rem", whiteSpace: "pre-wrap", maxWidth: "20rem" }}>{finding.output || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
