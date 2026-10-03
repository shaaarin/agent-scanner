import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Scan, AgentConfig, ScanResults, ScanLog, CodeScanResults as CodeScanResultsData } from "../api/types";
import { SCAN_PHASES, scanTypeLabel } from "../api/scanTypes";
import { PageHeader } from "../components/PageHeader";
import { CodeScanResults } from "../components/CodeScanResults";

const TERMINAL_STATUSES = ["completed", "failed"];

export function ScansDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [scan, setScan] = useState<Scan | null>(null);
  const [agentConfig, setAgentConfig] = useState<AgentConfig | null>(null);
  const [results, setResults] = useState<ScanResults | null>(null);
  const [logs, setLogs] = useState<ScanLog[]>([]);
  const [starting, setStarting] = useState(false);
  const logEndRef = useRef<HTMLDivElement | null>(null);
  const lastLogIdRef = useRef(0);

  useEffect(() => {
    if (!id) return;
    api.get<Scan>(`/scans/${id}`).then(setScan);
    api.get<AgentConfig>(`/scans/${id}/agent-config`).then(setAgentConfig).catch(() => {});
    api.get<ScanLog[]>(`/scans/${id}/logs`).then((initial) => {
      setLogs(initial);
      lastLogIdRef.current = initial.length ? initial[initial.length - 1].id : 0;
    });
  }, [id]);

  useEffect(() => {
    if (scan?.results) {
      try {
        setResults(JSON.parse(scan.results));
      } catch (error) {
        console.error("Failed to parse results:", error);
      }
    }
  }, [scan?.results]);

  useEffect(() => {
    if (!id || (scan && TERMINAL_STATUSES.includes(scan.status))) return;
    const timer = setInterval(async () => {
      try {
        const fresh = await api.get<Scan>(`/scans/${id}`);
        setScan(fresh);
        const freshLogs = await api.get<ScanLog[]>(`/scans/${id}/logs?after_id=${lastLogIdRef.current}`);
        if (freshLogs.length) {
          lastLogIdRef.current = freshLogs[freshLogs.length - 1].id;
          setLogs((prev) => [...prev, ...freshLogs]);
        }
      } catch (error) {
        console.error("Failed to poll scan:", error);
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [id, scan?.status]);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs.length]);

  const handleStart = async () => {
    if (!id) return;
    setStarting(true);
    try {
      const fresh = await api.post<Scan>(`/scans/${id}/start`, {});
      setScan(fresh);
    } catch (error) {
      console.error("Failed to start scan:", error);
    } finally {
      setStarting(false);
    }
  };

  const getStatusBadge = (status: string) => {
    const colors: Record<string, string> = {
      pending: "badge-secondary",
      running: "badge-primary",
      completed: "badge-success",
      failed: "badge-danger",
    };
    const labels: Record<string, string> = {
      pending: "Ожидает",
      running: "Выполняется",
      completed: "Завершено",
      failed: "Ошибка",
    };
    return <span className={`badge ${colors[status] || "badge-secondary"}`}>{labels[status] || status}</span>;
  };

  const phases = scan ? SCAN_PHASES[scan.type] ?? [] : [];
  const currentPhaseIndex = scan?.phase ? phases.indexOf(scan.phase) : -1;

  if (!scan) {
    return <div>Загрузка сканирования…</div>;
  }

  if (scan.type === "mcp" || scan.type === "agent_skills") {
    return (
      <div>
      <PageHeader
        title={scan.name}
        description={`${scanTypeLabel(scan.type)} · сканирование`}
      />
      <div className="card" style={{ padding: "3.2rem", textAlign: "center" }}>
        <h2 style={{ marginBottom: "1rem" }}>В разработке</h2>
        <p style={{ color: "var(--text-600)", margin: 0 }}>
          Сканирование типа {scanTypeLabel(scan.type)} пока не реализовано.
        </p>
        <button className="btn btn-secondary" onClick={() => navigate("/scans")} style={{ marginTop: "1.6rem" }}>
          Назад к списку
        </button>
      </div>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title={scan.name}
        description={`${scanTypeLabel(scan.type)} · сканирование`}
        actions={
          <div style={{ display: "flex", gap: "0.5rem" }}>
            {scan.status === "pending" && (
              <button className="btn btn-primary" onClick={handleStart} disabled={starting}>
                {starting ? "Запуск…" : "Запустить"}
              </button>
            )}
            <button className="btn btn-secondary" onClick={() => navigate("/scans")}>
              ← Назад
            </button>
          </div>
        }
      />

      <div className="card" style={{ marginBottom: "2rem" }}>
        <h3 style={{ marginBottom: "1rem" }}>Общие сведения</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "1rem" }}>
          <div>
            <div style={{ color: "var(--text-600)", fontSize: "0.9rem" }}>Статус</div>
            <div style={{ marginTop: "0.25rem" }}>{getStatusBadge(scan.status)}</div>
          </div>
          <div>
            <div style={{ color: "var(--text-600)", fontSize: "0.9rem" }}>Тип</div>
            <div style={{ marginTop: "0.25rem" }}>{scanTypeLabel(scan.type)}</div>
          </div>
          <div>
            <div style={{ color: "var(--text-600)", fontSize: "0.9rem" }}>Агент</div>
            <div style={{ marginTop: "0.25rem" }}>{agentConfig?.name || "-"}</div>
          </div>
          <div>
            <div style={{ color: "var(--text-600)", fontSize: "0.9rem" }}>Создано</div>
            <div style={{ marginTop: "0.25rem" }}>
              {new Date(scan.created_at).toLocaleString("ru-RU")}
            </div>
          </div>
          {scan.started_at && (
            <div>
              <div style={{ color: "var(--text-600)", fontSize: "0.9rem" }}>Начато</div>
              <div style={{ marginTop: "0.25rem" }}>
                {new Date(scan.started_at).toLocaleString("ru-RU")}
              </div>
            </div>
          )}
          {scan.finished_at && (
            <div>
              <div style={{ color: "var(--text-600)", fontSize: "0.9rem" }}>Завершено</div>
              <div style={{ marginTop: "0.25rem" }}>
                {new Date(scan.finished_at).toLocaleString("ru-RU")}
              </div>
            </div>
          )}
        </div>
      </div>

      {(scan.status === "running" || scan.status === "completed" || scan.status === "failed") && (
        <div className="card" style={{ marginBottom: "2rem" }}>
          <h3 style={{ marginBottom: "1rem" }}>Прогресс</h3>

          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginBottom: "1.5rem" }}>
            {phases.map((phase, index) => {
              const done = currentPhaseIndex >= 0 && index < currentPhaseIndex;
              const current = index === currentPhaseIndex;
              const color = scan.status === "failed" && current
                ? "var(--danger)"
                : done || (current && scan.status === "completed")
                ? "var(--success, #2e7d32)"
                : current
                ? "var(--primary, #1976d2)"
                : "var(--separator-default)";
              return (
                <div
                  key={phase}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.4rem",
                    padding: "0.35rem 0.7rem",
                    borderRadius: "var(--radius-m)",
                    border: `0.1rem solid ${color}`,
                    color: current || done ? color : "var(--text-600)",
                    background: current ? "var(--background-generic)" : "transparent",
                    fontSize: "0.85rem",
                  }}
                >
                  <span style={{ fontWeight: current ? 600 : 400 }}>{phase}</span>
                </div>
              );
            })}
          </div>

          <div
            style={{
              background: "#0f172a",
              color: "#e2e8f0",
              borderRadius: "var(--radius-m)",
              padding: "1rem",
              maxHeight: "360px",
              overflow: "auto",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
              fontSize: "0.8rem",
              lineHeight: 1.5,
            }}
          >
            {logs.length === 0 ? (
              <div style={{ color: "#94a3b8" }}>Журнал появится здесь после запуска сканирования.</div>
            ) : (
              logs.map((log) => (
                <div
                  key={log.id}
                  style={{
                    color: log.level === "error" ? "#f87171" : log.level === "success" ? "#4ade80" : "#e2e8f0",
                    whiteSpace: "pre-wrap",
                  }}
                >
                  <span style={{ color: "#64748b" }}>
                    {new Date(log.created_at).toLocaleTimeString("ru-RU")}
                  </span>{" "}
                  {log.message}
                </div>
              ))
            )}
            <div ref={logEndRef} />
          </div>
        </div>
      )}

      {scan.status === "pending" && (
        <div className="card" style={{ padding: "3.2rem", textAlign: "center" }}>
          <p style={{ color: "var(--text-700)", fontWeight: 500, margin: 0 }}>
            Сканирование ещё не запускалось
          </p>
          <p style={{ color: "var(--text-500)", fontSize: 13, margin: "0.6rem 0 0" }}>
            {scan.type === "code_scan"
              ? "Платформа скачает код агента и проверит его через promptfoo. Агент при этом не запускается."
              : "Платформа соберёт агента, поднимет его и проверит ответы на выбранные атаки."}
          </p>
          <button className="btn btn-primary" onClick={handleStart} disabled={starting} style={{ marginTop: "1.6rem" }}>
            {starting ? "Запуск…" : "Запустить сканирование"}
          </button>
        </div>
      )}

      {scan.status === "failed" && (scan.error || results?.error) && (
        <div className="card" style={{ padding: "2rem", borderLeft: "0.3rem solid var(--danger)" }}>
          <h3 style={{ color: "var(--danger)", marginBottom: "1rem" }}>Ошибка</h3>
          <p style={{ color: "var(--text-700)" }}>{scan.error || results?.error}</p>
        </div>
      )}

      {scan.status === "completed" && results && scan.type === "code_scan" && (
        <CodeScanResults results={results as unknown as CodeScanResultsData} />
      )}

      {results && scan.type !== "code_scan" &&
        (scan.status === "completed" || (scan.status === "failed" && (results.vulnerability_results?.length ?? 0) > 0)) && (
        <div className="card" style={{ padding: "2rem", marginTop: scan.status === "failed" ? "2rem" : undefined }}>
          <h3 style={{ marginBottom: "1.5rem" }}>{scan.status === "failed" ? "Кейсы" : "Результаты"}</h3>

          {scan.status === "completed" && results.overall_score !== undefined && (
            <div style={{ marginBottom: "2rem", padding: "1.2rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
              <div style={{ color: "var(--text-600)", fontSize: "0.9rem" }}>Доля пройденных проверок</div>
              <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.5rem" }}>
                {Math.round(results.overall_score * 100)}%
              </div>
            </div>
          )}

          {results.vulnerability_results && results.vulnerability_results.length > 0 && (
            <div>
              <h4 style={{ marginBottom: "1rem" }}>Разбивка по уязвимостям</h4>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                    <th style={{ padding: "0.75rem", textAlign: "left" }}>Уязвимость</th>
                    <th style={{ padding: "0.75rem", textAlign: "left" }}>Статус</th>
                    <th style={{ padding: "0.75rem", textAlign: "left" }}>Защита</th>
                    <th style={{ padding: "0.75rem", textAlign: "left" }}>Обоснование</th>
                  </tr>
                </thead>
                <tbody>
                  {results.vulnerability_results.map((result, index) => (
                    <tr key={index} style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                      <td style={{ padding: "0.75rem" }}>{result.vulnerability}</td>
                      <td style={{ padding: "0.75rem" }}>
                        {result.errored ? (
                          <span className="badge badge-warning">Ошибка</span>
                        ) : (
                          <span className={`badge ${result.passed ? "badge-success" : "badge-danger"}`}>
                            {result.passed ? "Устойчив" : "Уязвим"}
                          </span>
                        )}
                      </td>
                      <td style={{ padding: "0.75rem" }}>
                        {result.errored ? "—" : `${Math.round(result.score * 100)}%`}
                      </td>
                      <td style={{ padding: "0.75rem", fontSize: "0.9rem", color: "var(--text-600)" }}>
                        {result.reasoning}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
