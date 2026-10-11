import { Fragment, useState } from "react";
import type { CodeScanFinding, CodeScanResults as CodeScanResultsData } from "../api/types";
import { SEVERITY_BADGES, SEVERITY_LABELS, SEVERITY_ORDER } from "../api/scanTypes";

function location(finding: CodeScanFinding): string {
  if (!finding.file) return "—";
  if (finding.start_line && finding.line && finding.start_line !== finding.line) {
    return `${finding.file}:${finding.start_line}–${finding.line}`;
  }
  return finding.line ? `${finding.file}:${finding.line}` : finding.file;
}

function formatDuration(seconds?: number): string | null {
  if (seconds === undefined || seconds === null) return null;
  const minutes = Math.floor(seconds / 60);
  return minutes > 0 ? `${minutes} мин ${seconds % 60} с` : `${seconds} с`;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="btn btn-sm btn-secondary"
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard
          .writeText(text)
          .then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          })
          .catch(() => {});
      }}
    >
      {copied ? "Скопировано" : "Скопировать"}
    </button>
  );
}

const blockStyle = {
  padding: "1rem",
  background: "var(--background-generic)",
  borderRadius: "var(--radius-m)",
  whiteSpace: "pre-wrap" as const,
  fontSize: "0.9rem",
};

export function CodeScanResults({ results }: { results: CodeScanResultsData }) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const findings = results.findings ?? [];
  const meta = [
    results.commit && `коммит ${results.commit.slice(0, 12)}`,
    results.git_ref && `ветка ${results.git_ref}`,
    results.files_in_scope !== undefined && `файлов в анализе: ${results.files_in_scope}`,
    results.min_severity && `порог: ${SEVERITY_LABELS[results.min_severity] ?? results.min_severity}`,
    formatDuration(results.duration_sec) && `длительность ${formatDuration(results.duration_sec)}`,
    results.engine_version && `${results.engine_label ?? "promptfoo"} ${results.engine_version}`,
  ].filter(Boolean);

  return (
    <div className="card" style={{ padding: "2rem" }}>
      <h3 style={{ marginBottom: "0.5rem" }}>Результаты анализа кода</h3>
      {meta.length > 0 && (
        <p style={{ margin: "0 0 1.5rem", color: "var(--text-600)", fontSize: "0.85rem" }}>{meta.join(" · ")}</p>
      )}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
          gap: "1rem",
          marginBottom: "1.5rem",
        }}
      >
        <div style={{ padding: "1rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
          <div style={{ color: "var(--text-600)", fontSize: "0.85rem" }}>Всего проблем</div>
          <div style={{ fontSize: "1.8rem", fontWeight: "bold", marginTop: "0.3rem" }}>{results.summary?.total ?? findings.length}</div>
        </div>
        {SEVERITY_ORDER.map((severity) => (
          <div
            key={severity}
            style={{ padding: "1rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}
          >
            <span className={`badge ${SEVERITY_BADGES[severity]}`}>{SEVERITY_LABELS[severity]}</span>
            <div style={{ fontSize: "1.8rem", fontWeight: "bold", marginTop: "0.3rem" }}>
              {results.summary?.[severity] ?? 0}
            </div>
          </div>
        ))}
      </div>

      {results.review && (
        <div style={{ marginBottom: "1.5rem" }}>
          <h4 style={{ marginBottom: "0.6rem" }}>Общий вывод сканера</h4>
          <div style={blockStyle}>{results.review}</div>
        </div>
      )}

      {findings.length === 0 ? (
        <p style={{ margin: 0, color: "var(--text-700)", fontWeight: 500 }}>Проблем не найдено.</p>
      ) : (
        <div>
          <h4 style={{ marginBottom: "0.6rem" }}>Находки</h4>
          <p style={{ margin: "0 0 1rem", color: "var(--text-500)", fontSize: 13 }}>
            Нажмите на строку, чтобы увидеть рекомендацию по исправлению.
          </p>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                <th style={{ padding: "0.75rem", textAlign: "left" }}>Серьёзность</th>
                <th style={{ padding: "0.75rem", textAlign: "left" }}>Где</th>
                <th style={{ padding: "0.75rem", textAlign: "left" }}>Описание</th>
              </tr>
            </thead>
            <tbody>
              {findings.map((finding, index) => {
                const isOpen = expanded === index;
                return (
                  <Fragment key={index}>
                    <tr
                      onClick={() => setExpanded(isOpen ? null : index)}
                      style={{
                        borderBottom: isOpen ? "none" : "0.1rem solid var(--separator-default)",
                        cursor: "pointer",
                        verticalAlign: "top",
                      }}
                    >
                      <td style={{ padding: "0.75rem", whiteSpace: "nowrap" }}>
                        <span className={`badge ${SEVERITY_BADGES[finding.severity]}`}>
                          {SEVERITY_LABELS[finding.severity] ?? finding.severity}
                        </span>
                      </td>
                      <td
                        style={{
                          padding: "0.75rem",
                          fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
                          fontSize: "0.8rem",
                          wordBreak: "break-all",
                        }}
                      >
                        {location(finding)}
                      </td>
                      <td style={{ padding: "0.75rem", fontSize: "0.9rem", whiteSpace: "pre-wrap" }}>{finding.finding}</td>
                    </tr>
                    {isOpen && (
                      <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                        <td colSpan={3} style={{ padding: "0 0.75rem 1rem" }}>
                          <div style={{ marginBottom: "0.8rem" }}>
                            <div style={{ color: "var(--text-600)", fontSize: "0.85rem", marginBottom: "0.4rem" }}>
                              Рекомендация
                            </div>
                            <div style={blockStyle}>{finding.fix || "Сканер не предложил исправление."}</div>
                          </div>
                          {finding.ai_agent_prompt && (
                            <div>
                              <div
                                style={{
                                  display: "flex",
                                  justifyContent: "space-between",
                                  alignItems: "center",
                                  color: "var(--text-600)",
                                  fontSize: "0.85rem",
                                  marginBottom: "0.4rem",
                                }}
                              >
                                <span>Промпт для AI-ассистента</span>
                                <CopyButton text={finding.ai_agent_prompt} />
                              </div>
                              <div style={blockStyle}>{finding.ai_agent_prompt}</div>
                            </div>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
