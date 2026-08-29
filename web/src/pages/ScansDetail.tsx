import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Scan, AgentConfig, ScanResults } from "../api/types";
import { PageHeader } from "../components/PageHeader";

export function ScansDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [scan, setScan] = useState<Scan | null>(null);
  const [agentConfig, setAgentConfig] = useState<AgentConfig | null>(null);
  const [results, setResults] = useState<ScanResults | null>(null);

  useEffect(() => {
    if (!id) return;

    Promise.all([
      api.get<Scan>(`/scans/${id}`).then(setScan),
      api.get<Scan>(`/scans/${id}`).then(s => 
        s ? api.get<AgentConfig>(`/scans/${id}/agent-config`).then(setAgentConfig) : null
      ),
    ]);
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

  const getStatusBadge = (status: string) => {
    const colors: Record<string, string> = {
      pending: "badge-secondary",
      running: "badge-primary",
      completed: "badge-success",
      failed: "badge-danger",
    };
    return <span className={`badge ${colors[status] || "badge-secondary"}`}>{status}</span>;
  };

  const getTypeLabel = (type: string) => {
    const labels: Record<string, string> = {
      deep_team: "DeepTeam",
      mcp: "MCP",
      agent_skills: "Agent Skills",
    };
    return labels[type] || type;
  };

  if (!scan) {
    return <div>Загрузка...</div>;
  }

  if (scan.type === "mcp" || scan.type === "agent_skills") {
    return (
      <div>
        <PageHeader
          title={scan.name}
          description={`${getTypeLabel(scan.type)} сканирование`}
        />
        <div className="card" style={{ padding: "2rem", textAlign: "center" }}>
          <h2 style={{ marginBottom: "1rem" }}>В разработке</h2>
          <p style={{ color: "var(--text-600)" }}>
            Сканирование типа {getTypeLabel(scan.type)} пока не реализовано.
          </p>
          <button className="btn btn-secondary" onClick={() => navigate("/scans")} style={{ marginTop: "1rem" }}>
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
        description={`${getTypeLabel(scan.type)} сканирование`}
        actions={
          <button className="btn btn-secondary" onClick={() => navigate("/scans")}>
            ← Назад
          </button>
        }
      />

      <div className="card" style={{ marginBottom: "2rem" }}>
        <h3 style={{ marginBottom: "1rem" }}>Информация о сканировании</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "1rem" }}>
          <div>
            <div style={{ color: "var(--text-600)", fontSize: "0.9rem" }}>Статус</div>
            <div style={{ marginTop: "0.25rem" }}>{getStatusBadge(scan.status)}</div>
          </div>
          <div>
            <div style={{ color: "var(--text-600)", fontSize: "0.9rem" }}>Тип</div>
            <div style={{ marginTop: "0.25rem" }}>{getTypeLabel(scan.type)}</div>
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
         </div>
       </div>

      {scan.status === "pending" && (
        <div className="card" style={{ padding: "2rem", textAlign: "center" }}>
          <p style={{ color: "var(--text-600)" }}>
            Сканирование ожидает запуска. Перейдите на страницу сканирований для запуска.
          </p>
          <button
            className="btn btn-primary"
            onClick={() => navigate("/scans")}
            style={{ marginTop: "1rem" }}
          >
            Перейти к сканированиям
          </button>
        </div>
      )}

      {scan.status === "running" && (
        <div className="card" style={{ padding: "2rem", textAlign: "center" }}>
          <div className="badge badge-primary" style={{ marginBottom: "1rem" }}>Выполняется</div>
          <p style={{ color: "var(--text-600)" }}>
            DeepTeam сканирование в процессе выполнения. Результаты появятся здесь после завершения.
          </p>
        </div>
      )}

      {scan.status === "failed" && results?.error && (
        <div className="card" style={{ padding: "2rem", borderLeft: "0.3rem solid var(--danger)" }}>
          <h3 style={{ color: "var(--danger)", marginBottom: "1rem" }}>Ошибка</h3>
          <p style={{ color: "var(--text-700)" }}>{results.error}</p>
        </div>
      )}

      {scan.status === "completed" && results && (
        <div className="card" style={{ padding: "2rem" }}>
          <h3 style={{ marginBottom: "1.5rem" }}>Результаты сканирования</h3>
          
          {results.overall_score !== undefined && (
            <div style={{ marginBottom: "2rem", padding: "1rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" }}>
              <div style={{ color: "var(--text-600)", fontSize: "0.9rem" }}>Общая оценка</div>
              <div style={{ fontSize: "2rem", fontWeight: "bold", marginTop: "0.5rem" }}>
                {Math.round(results.overall_score * 100)}%
              </div>
            </div>
          )}

          {results.vulnerability_results && results.vulnerability_results.length > 0 && (
            <div>
              <h4 style={{ marginBottom: "1rem" }}>Результаты по уязвимостям</h4>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                    <th style={{ padding: "0.75rem", textAlign: "left" }}>Уязвимость</th>
                    <th style={{ padding: "0.75rem", textAlign: "left" }}>Статус</th>
                    <th style={{ padding: "0.75rem", textAlign: "left" }}>Оценка</th>
                    <th style={{ padding: "0.75rem", textAlign: "left" }}>Обоснование</th>
                  </tr>
                </thead>
                <tbody>
                  {results.vulnerability_results.map((result, index) => (
                    <tr key={index} style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                      <td style={{ padding: "0.75rem" }}>{result.vulnerability}</td>
                      <td style={{ padding: "0.75rem" }}>
                        <span className={`badge ${result.passed ? "badge-success" : "badge-danger"}`}>
                          {result.passed ? "Пройдено" : "Не пройдено"}
                        </span>
                      </td>
                      <td style={{ padding: "0.75rem" }}>{Math.round(result.score * 100)}%</td>
                      <td style={{ padding: "0.75rem", fontSize: "0.9rem", color: "var(--text-600)" }}>
                        {result.reasoning}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {!results.vulnerability_results || results.vulnerability_results.length === 0 && (
            <p style={{ color: "var(--text-600)" }}>Нет результатов по уязвимостям</p>
          )}
        </div>
      )}
    </div>
  );
}