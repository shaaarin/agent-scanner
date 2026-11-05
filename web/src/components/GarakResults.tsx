import type { GarakResults as ResultsData, GarakProbeEval, GarakHit } from "../api/types";

function flagColor(rate: number): string {
  if (rate >= 0.5) return "var(--danger)";
  if (rate > 0) return "var(--warning, #b7791f)";
  return "var(--success, #2e7d32)";
}

function ProbeTable({ rows }: { rows: GarakProbeEval[] }) {
  if (!rows.length) return null;
  // Сворачиваем до уровня пробы: одна строка на пробу, детекторы -- во всплывающем списке.
  const byProbe = new Map<string, { passed: number; total: number; detectors: string[] }>();
  for (const row of rows) {
    const cell = byProbe.get(row.probe) ?? { passed: 0, total: 0, detectors: [] };
    cell.passed += row.passed;
    cell.total += row.total;
    cell.detectors.push(row.detector);
    byProbe.set(row.probe, cell);
  }
  return (
    <table style={{ width: "100%", borderCollapse: "collapse" }}>
      <thead>
        <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
          <th style={{ padding: "0.6rem", textAlign: "left" }}>Проба</th>
          <th style={{ padding: "0.6rem", textAlign: "right" }}>Проверок</th>
          <th style={{ padding: "0.6rem", textAlign: "right" }}>Сработало</th>
          <th style={{ padding: "0.6rem", textAlign: "right" }}>Доля срабатываний</th>
          <th style={{ padding: "0.6rem", textAlign: "left" }}>Детекторы</th>
        </tr>
      </thead>
      <tbody>
        {[...byProbe.entries()].map(([probe, cell]) => {
          const flagged = cell.total - cell.passed;
          const rate = cell.total ? flagged / cell.total : 0;
          return (
            <tr key={probe} style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
              <td style={{ padding: "0.6rem", fontFamily: "ui-monospace, monospace", fontSize: "0.85rem" }}>{probe}</td>
              <td style={{ padding: "0.6rem", textAlign: "right" }}>{cell.total}</td>
              <td style={{ padding: "0.6rem", textAlign: "right", color: flagged ? "var(--danger)" : undefined }}>{flagged}</td>
              <td style={{ padding: "0.6rem", textAlign: "right", fontWeight: 600, color: flagColor(rate) }}>{Math.round(rate * 100)}%</td>
              <td style={{ padding: "0.6rem", fontSize: "0.8rem", color: "var(--text-600)" }}>{cell.detectors.join(", ")}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function HitTable({ hits }: { hits: GarakHit[] }) {
  if (!hits.length) return null;
  return (
    <table style={{ width: "100%", borderCollapse: "collapse" }}>
      <thead>
        <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
          <th style={{ padding: "0.6rem", textAlign: "left" }}>Проба</th>
          <th style={{ padding: "0.6rem", textAlign: "left" }}>Детектор</th>
          <th style={{ padding: "0.6rem", textAlign: "left" }}>Атака</th>
          <th style={{ padding: "0.6rem", textAlign: "left" }}>Ответ агента</th>
        </tr>
      </thead>
      <tbody>
        {hits.map((hit, index) => (
          <tr key={index} style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
            <td style={{ padding: "0.6rem", fontFamily: "ui-monospace, monospace", fontSize: "0.85rem" }}>{hit.probe}</td>
            <td style={{ padding: "0.6rem", fontFamily: "ui-monospace, monospace", fontSize: "0.85rem" }}>{hit.detector}</td>
            <td style={{ padding: "0.6rem", fontSize: "0.85rem", whiteSpace: "pre-wrap", maxWidth: "20rem" }}>{hit.prompt || "—"}</td>
            <td style={{ padding: "0.6rem", fontSize: "0.85rem", whiteSpace: "pre-wrap", maxWidth: "20rem" }}>{hit.output || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function GarakResults({ results }: { results: ResultsData }) {
  const s = results.summary;
  return (
    <div className="card" style={{ padding: "2rem" }}>
      <h3 style={{ marginBottom: "1.5rem" }}>Результаты · garak</h3>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "1rem", marginBottom: "2rem" }}>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Доля срабатываний</div>
          <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.4rem", color: flagColor(s.flag_rate) }}>
            {Math.round(s.flag_rate * 100)}%
          </div>
        </div>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Сработало детекторов</div>
          <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.4rem", color: s.flagged ? "var(--danger)" : undefined }}>{s.flagged}</div>
        </div>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Проверок</div>
          <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.4rem" }}>{s.evaluated}</div>
        </div>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Проб запущено</div>
          <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.4rem" }}>{s.probes_run}</div>
        </div>
      </div>

      <p style={{ color: "var(--text-500)", fontSize: 13, marginTop: 0, marginBottom: "2rem" }}>
        Проба «сработала», если рекомендованный детектор нашёл уязвимый ответ агента (порог garak по умолчанию — 0.5).
        Доля срабатываний = сработавшие проверки / все проверки.
        {results.engine_version ? ` Движок: garak ${results.engine_version}.` : ""}
      </p>

      <h4 style={{ marginBottom: "1rem" }}>По пробам</h4>
      <div style={{ marginBottom: "2rem" }}>
        <ProbeTable rows={results.probes} />
      </div>

      {results.hits.length > 0 && (
        <>
          <h4 style={{ marginBottom: "1rem" }}>Сработавшие атаки ({results.hits.length})</h4>
          <HitTable hits={results.hits} />
        </>
      )}
    </div>
  );
}
