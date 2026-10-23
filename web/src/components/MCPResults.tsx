import { SEVERITY_LABELS, SEVERITY_BADGES } from "../api/scanTypes";
import type { CodeScanSeverity } from "../api/types";

type Finding = {rule_id: string; severity: string; title: string; target: string; file?: string; line?: number; evidence: unknown; recommendation: string; category: string};
export type MCPResultData = {engine_name: string; engine_version: string; duration_sec: number; coverage: string; findings: Finding[]; status?: "running" | "completed" | "completed_with_errors" | "failed" | "success" | "partially_failed"; error?: string | null; summary?: {total: number; completed: number; failed: number; pending: number}; checks?: {name: string; status: string; evidence: string}[]; files_checked?: number; tools_checked?: number; commit?: string; raw?: unknown; runs?: MCPResultData[]};
export function MCPResults({results: r}: {results: MCPResultData}) {
  const status = r.status === "completed" ? "success" : r.status === "completed_with_errors"
    ? (r.summary?.completed === 0 ? "failed" : "partially_failed") : r.status;
  const incomplete = status === "failed" || status === "running" || status === "partially_failed" || !!(r.summary && (r.summary.failed || r.summary.pending));
  return <div className="card" style={{padding: "2rem", marginTop: "2rem"}}>
    <h2>Результаты MCP-проверки</h2>
    <p>{r.engine_name} · {r.engine_version} · {r.duration_sec} с{r.files_checked !== undefined && ` · файлов: ${r.files_checked}`}{r.tools_checked !== undefined && ` · инструментов: ${r.tools_checked}`}</p>
    {status && <p><span className={`badge ${status === "success" ? "badge-success" : status === "partially_failed" ? "badge-warning" : status === "running" ? "badge-secondary" : "badge-danger"}`}>{({running: "Промежуточные результаты", success: "Успешно выполнено", partially_failed: "Частично выполнено", failed: "Ошибка"})[status]}</span></p>}
    {r.summary && <p>Движков: {r.summary.total} · завершено успешно: {r.summary.completed} · ошибок: {r.summary.failed} · без окончательного результата: {r.summary.pending}</p>}
    {incomplete && <p role="alert">Покрытие неполное. Отсутствие находок у незавершённых или завершившихся ошибкой движков не означает безопасность цели.</p>}
    {r.error && <p style={{whiteSpace: "pre-wrap", overflowWrap: "anywhere"}}>Ошибка: {r.error}</p>}
    {r.commit && <p>Коммит: <code>{r.commit}</code></p>}
    <p style={{color: "var(--text-500)"}}>{r.coverage}</p>
    {r.checks && <><h3>Выполненные проверки</h3>{r.checks.map((c,i)=><details key={i} style={{margin: "1rem 0"}}><summary><span className={`badge ${c.status === "passed" ? "badge-success" : "badge-danger"}`}>{c.status === "passed" ? "Пройдена" : "Не пройдена"}</span> {c.name}</summary><pre style={{whiteSpace: "pre-wrap", overflowWrap: "anywhere"}}>{c.evidence}</pre></details>)}</>}
    {status !== "failed" && <h3>Находки: {r.findings.length}</h3>}
    {!r.findings.length && !incomplete && <p>В пределах выполненных правил находок нет. Это не заключение о полной безопасности MCP-сервера.</p>}
    {r.findings.map((f,i)=><details key={i} style={{padding: "1rem 0", borderBottom: "1px solid var(--separator-default)"}}><summary><span className={`badge ${SEVERITY_BADGES[f.severity as CodeScanSeverity] ?? "badge-secondary"}`}>{SEVERITY_LABELS[f.severity as CodeScanSeverity] ?? f.severity}</span> {f.title}<p><code>{f.file ?? f.target}{f.line ? `:${f.line}` : ""}</code> · {f.rule_id} · {f.category}</p></summary><h4>Основание</h4><pre style={{whiteSpace: "pre-wrap", overflowWrap: "anywhere"}}>{typeof f.evidence === "string" ? f.evidence : JSON.stringify(f.evidence, null, 2)}</pre><h4>Рекомендация</h4><p>{f.recommendation}</p></details>)}
    {r.runs?.map((run,i) => <MCPResults key={i} results={run} />)}
    {r.raw !== undefined && <details style={{marginTop: "2rem"}}><summary>Исходный JSON-отчёт движка</summary><pre style={{whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 500, overflow: "auto"}}>{JSON.stringify(r.raw, null, 2)}</pre></details>}
  </div>;
}
