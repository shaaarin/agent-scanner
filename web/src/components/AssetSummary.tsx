import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { AssetKind, AssetSummary as SummaryData, FindingSeverity } from "../api/types";
import { RatingBadge } from "./ScanReport";

// Сводка-дашборд карточки актива: оценка устойчивости, находки по
// серьёзности и разбивка по типам сканирований. Считает control-api
// (GET /assets/{kind}/{id}/summary) по последнему завершённому скану
// каждого типа, поэтому повторные прогоны не удваивают находки.

const SEVERITY_ORDER: FindingSeverity[] = ["critical", "high", "medium", "low", "info"];

const SEVERITY_SHORT: Record<FindingSeverity, string> = {
  critical: "Критич.",
  high: "Высокие",
  medium: "Средние",
  low: "Низкие",
  info: "Инфо",
};

const SEVERITY_COLORS: Record<FindingSeverity, string> = {
  critical: "var(--danger)",
  high: "var(--danger)",
  medium: "var(--warning, #b7791f)",
  low: "var(--text-700)",
  info: "var(--text-700)",
};

const RATING_HINTS: Record<string, string> = {
  protected: "Выполненные проверки не выявили значимых проблем.",
  partial: "Есть проблемы средней серьёзности или часть атак удалась.",
  unsafe: "Есть находки высокой/критической серьёзности или значительная доля успешных атак.",
  unknown: "Завершённых сканирований с результатом пока нет.",
};

function percent(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

export function AssetSummary({ kind, id, refreshKey = 0 }: { kind: AssetKind; id: number; refreshKey?: number }) {
  const navigate = useNavigate();
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<SummaryData>(`/assets/${kind}/${id}/summary`)
      .then(setSummary)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [kind, id, refreshKey]);

  if (error) {
    return (
      <div className="card" style={{ padding: "1.5rem", marginBottom: "1.5rem" }}>
        <span style={{ color: "var(--danger)" }}>Не удалось загрузить сводку: {error}</span>
      </div>
    );
  }
  if (!summary) return null;

  const { scans } = summary;

  return (
    <div className="card" style={{ padding: "1.5rem", marginBottom: "1.5rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.2rem" }}>
        <h3 style={{ margin: 0 }}>Сводка по активу</h3>
        <RatingBadge rating={summary.rating} label={summary.rating_label} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "1rem" }}>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Находок всего</div>
          <div
            style={{
              fontSize: "1.8rem",
              fontWeight: 700,
              marginTop: "0.4rem",
              color: summary.findings_total ? "var(--danger)" : undefined,
            }}
          >
            {summary.findings_total}
          </div>
        </div>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Сканирований</div>
          <div style={{ fontSize: "1.8rem", fontWeight: 700, marginTop: "0.4rem" }}>{scans.total}</div>
          <div style={{ color: "var(--text-500)", fontSize: 12, marginTop: "0.2rem" }}>
            завершено {scans.completed}
            {scans.running ? `, выполняется ${scans.running}` : ""}
            {scans.failed ? `, с ошибкой ${scans.failed}` : ""}
            {scans.pending ? `, ожидает ${scans.pending}` : ""}
          </div>
        </div>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>По серьёзности</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.8rem", marginTop: "0.6rem" }}>
            {SEVERITY_ORDER.filter((severity) => summary.by_severity[severity] > 0).map((severity) => (
              <div key={severity}>
                <span style={{ fontSize: "1.2rem", fontWeight: 700, color: SEVERITY_COLORS[severity] }}>
                  {summary.by_severity[severity]}
                </span>
                <span style={{ color: "var(--text-500)", fontSize: 12, marginLeft: "0.3rem" }}>{SEVERITY_SHORT[severity]}</span>
              </div>
            ))}
            {summary.findings_total === 0 && <span style={{ color: "var(--text-500)", fontSize: 13 }}>находок нет</span>}
          </div>
        </div>
        <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Последнее сканирование</div>
          <div style={{ fontSize: "1rem", fontWeight: 600, marginTop: "0.6rem" }}>
            {summary.last_scan_at ? new Date(summary.last_scan_at).toLocaleString("ru-RU") : "—"}
          </div>
        </div>
      </div>

      <p style={{ color: "var(--text-500)", fontSize: 13, margin: "1rem 0 0" }}>
        {RATING_HINTS[summary.rating]} Оценка и находки считаются по последнему завершённому сканированию каждого типа.
      </p>

      {summary.by_scan_type.length > 0 && (
        <>
          <h4 style={{ margin: "1.5rem 0 0.8rem" }}>По типам сканирований</h4>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                <th style={{ padding: "0.6rem", textAlign: "left", width: "100%" }}>Тип</th>
                <th style={{ padding: "0.6rem", textAlign: "left" }}>Оценка</th>
                <th style={{ padding: "0.6rem", textAlign: "right" }}>Находок</th>
                <th style={{ padding: "0.6rem", textAlign: "right" }}>Устойчивость</th>
                <th style={{ padding: "0.6rem", textAlign: "right" }}>Успешных атак</th>
                <th style={{ padding: "0.6rem", textAlign: "right" }}>Скан</th>
              </tr>
            </thead>
            <tbody>
              {summary.by_scan_type.map((row) => (
                <tr key={row.type} style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                  <td style={{ padding: "0.6rem" }}>{row.type_label}</td>
                  <td style={{ padding: "0.6rem" }}>
                    <RatingBadge rating={row.rating} label={row.rating_label} />
                  </td>
                  <td style={{ padding: "0.6rem", textAlign: "right", color: row.findings_total ? "var(--danger)" : undefined }}>
                    {row.findings_total}
                  </td>
                  <td style={{ padding: "0.6rem", textAlign: "right" }}>{percent(row.resistance_rate)}</td>
                  <td style={{ padding: "0.6rem", textAlign: "right" }}>{percent(row.attack_success_rate)}</td>
                  <td style={{ padding: "0.6rem", textAlign: "right" }}>
                    <button className="btn btn-sm btn-secondary" onClick={() => navigate(`/scans/${row.scan_id}`)}>
                      Открыть
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
