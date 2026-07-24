import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, generatorApi } from "../api/client";
import type { Campaign, FuzzAttempt, FuzzRun } from "../api/types";
import { PageHeader } from "../components/PageHeader";

const POLL_MS = 3000;

const statusLabel: Record<string, string> = {
  pending: "не запущен",
  running: "выполняется",
  paused: "на паузе",
  stopped: "остановлен",
  completed: "завершён",
};

const statusBadgeClass: Record<string, string> = {
  running: "badge-warning",
  completed: "badge-success",
  stopped: "badge-danger",
};

export function FuzzRunDetail() {
  const { id } = useParams();
  const fuzzRunId = Number(id);

  const [fuzzRun, setFuzzRun] = useState<FuzzRun | null>(null);
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [attempts, setAttempts] = useState<FuzzAttempt[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      Promise.all([
        api.get<FuzzRun>(`/fuzz-runs/${fuzzRunId}`),
        api.get<FuzzAttempt[]>(`/fuzz-runs/${fuzzRunId}/attempts`),
      ]).then(([fr, atts]) => {
        if (cancelled) return;
        setFuzzRun(fr);
        setAttempts(atts);
      });
    };
    load();
    const interval = setInterval(load, POLL_MS);
    return () => { cancelled = true; clearInterval(interval); };
  }, [fuzzRunId]);

  useEffect(() => {
    if (!fuzzRun) return;
    api.get<Campaign>(`/campaigns/${fuzzRun.base_campaign_id}`).then(setCampaign);
  }, [fuzzRun?.base_campaign_id]);

  async function handleStart() {
    setError(null);
    setBusy(true);
    try {
      await generatorApi.post(`/fuzz/${fuzzRunId}/start`, {});
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleStop() {
    setError(null);
    setBusy(true);
    try {
      await generatorApi.post(`/fuzz/${fuzzRunId}/stop`, {});
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!fuzzRun) {
    return <div style={{ padding: "var(--space-5)", color: "var(--text-500)" }}>Загрузка…</div>;
  }

  return (
    <div>
      <PageHeader
        title={fuzzRun.name}
        description={campaign ? `сканирование: ${campaign.name} (${campaign.session_id})` : undefined}
        actions={<Link to="/fuzz-runs" className="btn btn-secondary">← К списку</Link>}
      />

      {error && (
        <div className="card" style={{ borderColor: "var(--color-danger)", marginBottom: "var(--space-4)" }}>
          {error}
        </div>
      )}

      <div className="card" style={{ marginBottom: "var(--space-5)" }}>
        <p style={{ fontSize: 13 }}>
          статус: <span className={`badge ${statusBadgeClass[fuzzRun.status] ?? "badge-neutral"}`}>
            {statusLabel[fuzzRun.status] ?? fuzzRun.status}
          </span>
          {" · "}режим: {fuzzRun.mode}
          {" · "}макс. итераций: {fuzzRun.max_iterations}
          {" · "}итераций выполнено: {attempts.length}
        </p>
        <div style={{ display: "flex", gap: 8 }}>
          {(fuzzRun.status === "pending" || fuzzRun.status === "paused") && (
            <button className="btn" onClick={handleStart} disabled={busy}>Запустить</button>
          )}
          {fuzzRun.status === "running" && (
            <button className="btn btn-secondary" onClick={handleStop} disabled={busy}>Остановить</button>
          )}
        </div>
      </div>

      <h2>Попытки</h2>
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Сид-шаблон</th>
              <th>Стратегия</th>
              <th>Детектор</th>
              <th>Судья</th>
              <th>Reward</th>
              <th>Успех</th>
            </tr>
          </thead>
          <tbody>
            {attempts.map((a) => (
              <tr key={a.id}>
                <td>{a.iteration}</td>
                <td><code>#{a.seed_template_id}</code></td>
                <td>{a.mutation_strategy}</td>
                <td>
                  <span className={`badge ${a.detector_success ? "badge-danger" : "badge-neutral"}`}>
                    {a.detector_success ? "сработал" : "нет"}
                  </span>
                </td>
                <td title={a.judge_verdict}>{a.judge_score.toFixed(2)}</td>
                <td>{a.reward.toFixed(2)}</td>
                <td>
                  <span className={`badge ${a.success ? "badge-danger" : "badge-neutral"}`}>
                    {a.success ? "успех" : "нет"}
                  </span>
                </td>
              </tr>
            ))}
            {attempts.length === 0 && (
              <tr><td colSpan={7} style={{ color: "var(--color-text-muted)" }}>Попыток пока нет.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
