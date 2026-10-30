import { Fragment, useState } from "react";
import type { FindingSeverity, ReportConversationTurn, ReportFinding, ScanRating, ScanReport } from "../api/types";
import { CONTROL_API_URL } from "../api/client";

// Единый вид результатов для всех сканеров: оценка устойчивости, общие
// метрики и находки в одном формате. Данные берутся из GET /scans/{id}/report
// (нормализацию делает control-api), поэтому здесь нет логики по типам сканов
// -- только отображение.

const SEVERITY_ORDER: FindingSeverity[] = ["critical", "high", "medium", "low", "info"];

const SEVERITY_LABELS: Record<FindingSeverity, string> = {
  critical: "Критическая",
  high: "Высокая",
  medium: "Средняя",
  low: "Низкая",
  info: "Информационная",
};

const SEVERITY_BADGES: Record<FindingSeverity, string> = {
  critical: "badge-danger",
  high: "badge-danger",
  medium: "badge-warning",
  low: "badge-neutral",
  info: "badge-neutral",
};

export const RATING_BADGES: Record<ScanRating, string> = {
  protected: "badge-success",
  partial: "badge-warning",
  unsafe: "badge-danger",
  unknown: "badge-neutral",
};

export function RatingBadge({ rating, label }: { rating: ScanRating; label: string }) {
  return <span className={`badge ${RATING_BADGES[rating]}`}>{label}</span>;
}

function percent(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

function Tile({ label, value, color, hint }: { label: string; value: string; color?: string; hint?: string }) {
  return (
    <div style={{ padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
      <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>{label}</div>
      <div style={{ fontSize: "1.8rem", fontWeight: 700, marginTop: "0.4rem", color }}>{value}</div>
      {hint && <div style={{ color: "var(--text-500)", fontSize: 12, marginTop: "0.2rem" }}>{hint}</div>}
    </div>
  );
}

const ROLE_LABELS: Record<string, string> = {
  user: "Атакующий промпт",
  assistant: "Ответ агента",
  system: "Системное сообщение",
  tool: "Результат инструмента",
  _intercepted_request: "Перехваченный запрос к LLM",
};

function Conversation({ turns }: { turns: ReportConversationTurn[] }) {
  return (
    <div style={{ display: "grid", gap: "0.6rem" }}>
      {turns.map((turn, index) => (
        <div
          key={index}
          style={{
            padding: "0.8rem",
            borderRadius: "var(--radius-m)",
            border: `0.1rem solid ${turn.injected ? "var(--danger)" : "var(--separator-default)"}`,
            background: "var(--background-generic)",
          }}
        >
          <div style={{ fontSize: 12, color: "var(--text-500)", marginBottom: "0.3rem" }}>
            {ROLE_LABELS[turn.role] ?? turn.role}
            {turn.name ? ` · ${turn.name}` : ""}
            {turn.injected && <strong style={{ color: "var(--danger)" }}> · подмена платформы</strong>}
            {turn.note ? ` · ${turn.note}` : ""}
          </div>
          <pre style={{ margin: 0, whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontSize: "0.8rem", lineHeight: 1.5 }}>
            {turn.content}
          </pre>
        </div>
      ))}
    </div>
  );
}

function location(finding: ReportFinding): string {
  const loc = finding.location;
  if (!loc?.file) return finding.evidence?.target ? `цель: ${finding.evidence.target}` : "—";
  if (loc.start_line && loc.end_line && loc.end_line !== loc.start_line) {
    return `${loc.file}:${loc.start_line}–${loc.end_line}`;
  }
  return loc.start_line ? `${loc.file}:${loc.start_line}` : loc.file;
}

function FindingsTable({ findings }: { findings: ReportFinding[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [severityFilter, setSeverityFilter] = useState<FindingSeverity | "all">("all");
  const shown = severityFilter === "all" ? findings : findings.filter((f) => f.severity === severityFilter);

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h4 style={{ margin: 0 }}>Находки ({shown.length})</h4>
        <select
          className="input"
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value as FindingSeverity | "all")}
          style={{ width: "auto" }}
        >
          <option value="all">Все уровни</option>
          {SEVERITY_ORDER.map((severity) => (
            <option key={severity} value={severity}>
              {SEVERITY_LABELS[severity]}
            </option>
          ))}
        </select>
      </div>
      <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", minWidth: "62rem", tableLayout: "fixed", borderCollapse: "collapse" }}>
        <colgroup>
          <col style={{ width: "11rem" }} />
          <col />
          <col style={{ width: "22%" }} />
          <col style={{ width: "9rem" }} />
        </colgroup>
        <thead>
          <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
            <th style={{ padding: "0.6rem", textAlign: "left" }}>Серьёзность</th>
            <th style={{ padding: "0.6rem", textAlign: "left" }}>Находка</th>
            <th style={{ padding: "0.6rem", textAlign: "left" }}>Где</th>
            <th style={{ padding: "0.6rem", textAlign: "right" }}>Детали</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((finding) => (
            <Fragment key={finding.id}>
              <tr style={{ borderBottom: expanded === finding.id ? "none" : "0.1rem solid var(--separator-default)" }}>
                <td style={{ padding: "0.6rem" }}>
                  <span className={`badge ${SEVERITY_BADGES[finding.severity]}`} style={{ whiteSpace: "nowrap" }}>{SEVERITY_LABELS[finding.severity]}</span>
                </td>
                <td style={{ padding: "0.6rem", overflowWrap: "anywhere" }}>
                  {finding.title}
                  {finding.rule_id && (
                    <div style={{ fontSize: 12, color: "var(--text-500)", fontFamily: "ui-monospace, monospace" }}>{finding.rule_id}</div>
                  )}
                </td>
                <td style={{ padding: "0.6rem", fontSize: "0.8rem", fontFamily: "ui-monospace, monospace", overflowWrap: "anywhere" }}>
                  {location(finding)}
                </td>
                <td style={{ padding: "0.6rem", textAlign: "right" }}>
                  <button className="btn btn-sm btn-secondary" onClick={() => setExpanded(expanded === finding.id ? null : finding.id)}>
                    {expanded === finding.id ? "Скрыть" : "Показать"}
                  </button>
                </td>
              </tr>
              {expanded === finding.id && (
                <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                  <td colSpan={4} style={{ padding: "0 0.6rem 1.2rem" }}>
                    {finding.description && (
                      <>
                        <div style={{ color: "var(--text-600)", fontSize: "0.8rem", margin: "0.4rem 0" }}>Описание</div>
                        <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{finding.description}</p>
                      </>
                    )}
                    {finding.evidence?.conversation && finding.evidence.conversation.length > 0 && (
                      <>
                        <div style={{ color: "var(--text-600)", fontSize: "0.8rem", margin: "1rem 0 0.4rem" }}>Диалог атаки</div>
                        <Conversation turns={finding.evidence.conversation} />
                      </>
                    )}
                    {finding.evidence?.detail && !finding.evidence?.conversation?.length && (
                      <>
                        <div style={{ color: "var(--text-600)", fontSize: "0.8rem", margin: "1rem 0 0.4rem" }}>Основание</div>
                        <pre style={{ margin: 0, padding: "0.8rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)", whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontSize: "0.8rem" }}>
                          {finding.evidence.detail}
                        </pre>
                      </>
                    )}
                    {finding.recommendation && (
                      <>
                        <div style={{ color: "var(--text-600)", fontSize: "0.8rem", margin: "1rem 0 0.4rem" }}>Рекомендация</div>
                        <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{finding.recommendation}</p>
                      </>
                    )}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
      </div>
    </>
  );
}

export function ScanReportView({ report, children }: { report: ScanReport; children?: React.ReactNode }) {
  const { metrics, scan } = report;
  const isDynamic = metrics.analysis === "dynamic";
  // Выгрузка: диалоги успешных атак для динамики, SARIF для статики.
  const exportUrl = isDynamic
    ? `${CONTROL_API_URL}/scans/${scan.id}/export/attacks`
    : `${CONTROL_API_URL}/scans/${scan.id}/export/sarif`;
  const exportLabel = isDynamic ? "Скачать диалоги атак (JSON)" : "Скачать SARIF-отчёт";

  const engineLine = [
    report.engine.name,
    report.engine.version,
    report.engine.duration_sec != null ? `${report.engine.duration_sec} с` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="card" style={{ padding: "2rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "1rem", marginBottom: "1.5rem" }}>
        <div>
          <h3 style={{ margin: 0 }}>Отчёт сканирования</h3>
          {engineLine && <div style={{ color: "var(--text-500)", fontSize: 13, marginTop: "0.3rem" }}>{engineLine}</div>}
        </div>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <RatingBadge rating={report.rating} label={report.rating_label} />
          <a className="btn btn-sm btn-secondary" href={exportUrl} download>
            {exportLabel}
          </a>
          <a className="btn btn-sm btn-secondary" href={`${CONTROL_API_URL}/scans/${scan.id}/report`} target="_blank" rel="noreferrer">
            JSON
          </a>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "1rem", marginBottom: "1.5rem" }}>
        <Tile label="Находок" value={String(metrics.findings_total)} color={metrics.findings_total ? "var(--danger)" : undefined} />
        {metrics.by_severity.critical + metrics.by_severity.high > 0 && (
          <Tile
            label="Критич. и высокие"
            value={String(metrics.by_severity.critical + metrics.by_severity.high)}
            color="var(--danger)"
          />
        )}
        {metrics.checks_total != null && (
          <Tile
            label={isDynamic ? "Атак выполнено" : "Проверок"}
            value={String(metrics.checks_total)}
            hint={
              isDynamic
                ? `отражено ${metrics.checks_passed ?? 0}, успешных ${metrics.checks_failed ?? 0}`
                : `пройдено ${metrics.checks_passed ?? 0}, провалено ${metrics.checks_failed ?? 0}`
            }
          />
        )}
        {metrics.resistance_rate != null && (
          <Tile label="Устойчивость" value={percent(metrics.resistance_rate)} hint="доля отражённых проверок" />
        )}
        {metrics.attack_success_rate != null && (
          <Tile
            label="Доля успешных атак"
            value={percent(metrics.attack_success_rate)}
            color={metrics.attack_success_rate > 0 ? "var(--danger)" : undefined}
          />
        )}
      </div>

      {Boolean(metrics.checks_errored || metrics.checks_skipped) && (
        <p style={{ color: "var(--text-500)", fontSize: 13, marginTop: 0 }}>
          Не учтено в оценке: с ошибкой {metrics.checks_errored ?? 0}, без результата {metrics.checks_skipped ?? 0}.
        </p>
      )}

      {report.engine.coverage && (
        <p style={{ color: "var(--text-500)", fontSize: 13, marginTop: 0 }}>{report.engine.coverage}</p>
      )}

      {metrics.findings_total > 0 ? (
        <FindingsTable findings={report.findings} />
      ) : (
        <p style={{ color: "var(--text-600)" }}>
          Находок нет. Это результат выполненных проверок, а не заключение о полной безопасности актива.
        </p>
      )}

      {children && (
        <details style={{ marginTop: "2rem" }}>
          <summary style={{ cursor: "pointer", color: "var(--text-600)" }}>Отчёт сканера как есть</summary>
          <div style={{ marginTop: "1rem" }}>{children}</div>
        </details>
      )}
    </div>
  );
}
