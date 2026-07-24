import { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, generatorApi } from "../api/client";
import type { Campaign, ConversationNode, InjectionProbe, TreeRun } from "../api/types";
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

const stoppedReasonLabel: Record<string, string> = {
  success: "успех",
  natural_end: "естественное завершение",
  budget: "исчерпан бюджет ходов",
  stopped: "остановлено вручную",
};

export function TreeRunDetail() {
  const { id } = useParams();
  const treeRunId = Number(id);

  const [treeRun, setTreeRun] = useState<TreeRun | null>(null);
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [nodes, setNodes] = useState<ConversationNode[]>([]);
  const [probes, setProbes] = useState<InjectionProbe[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      Promise.all([
        api.get<TreeRun>(`/tree-runs/${treeRunId}`),
        api.get<ConversationNode[]>(`/tree-runs/${treeRunId}/nodes`),
        api.get<InjectionProbe[]>(`/tree-runs/${treeRunId}/probes`),
      ]).then(([tr, n, p]) => {
        if (cancelled) return;
        setTreeRun(tr);
        setNodes(n);
        setProbes(p);
      });
    };
    load();
    const interval = setInterval(load, POLL_MS);
    return () => { cancelled = true; clearInterval(interval); };
  }, [treeRunId]);

  useEffect(() => {
    if (!treeRun) return;
    api.get<Campaign>(`/campaigns/${treeRun.base_campaign_id}`).then(setCampaign);
  }, [treeRun?.base_campaign_id]);

  const checkpoints = useMemo(() => {
    const byOccurrence = new Map<number, InjectionProbe[]>();
    for (const p of probes) {
      const list = byOccurrence.get(p.checkpoint_occurrence) ?? [];
      list.push(p);
      byOccurrence.set(p.checkpoint_occurrence, list);
    }
    return [...byOccurrence.entries()]
      .sort(([a], [b]) => a - b)
      .map(([occurrence, attempts]) => ({
        occurrence,
        attempts: attempts.sort((a, b) => a.attempt_index - b.attempt_index),
      }));
  }, [probes]);

  async function handleStart() {
    setError(null);
    setBusy(true);
    try {
      await generatorApi.post(`/tree/${treeRunId}/start`, {});
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
      await generatorApi.post(`/tree/${treeRunId}/stop`, {});
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!treeRun) {
    return <div style={{ padding: "var(--space-5)", color: "var(--text-500)" }}>Загрузка…</div>;
  }

  return (
    <div>
      <PageHeader
        title={treeRun.name}
        description={campaign ? `сканирование: ${campaign.name} (${campaign.session_id})` : undefined}
        actions={<Link to="/tree-runs" className="btn btn-secondary">← К списку</Link>}
      />

      {error && (
        <div className="card" style={{ borderColor: "var(--color-danger)", marginBottom: "var(--space-4)" }}>
          {error}
        </div>
      )}

      <div className="card" style={{ marginBottom: "var(--space-5)" }}>
        <p style={{ fontSize: 13 }}>
          статус: <span className={`badge ${statusBadgeClass[treeRun.status] ?? "badge-neutral"}`}>
            {statusLabel[treeRun.status] ?? treeRun.status}
          </span>
          {" · "}ходов backbone: {nodes.length}/{treeRun.max_backbone_turns}
          {" · "}чекпоинтов найдено: {checkpoints.length}
          {" · "}попыток всего: {probes.length}
        </p>
        <div style={{ display: "flex", gap: 8 }}>
          {(treeRun.status === "pending" || treeRun.status === "paused") && (
            <button className="btn" onClick={handleStart} disabled={busy}>Запустить</button>
          )}
          {treeRun.status === "running" && (
            <button className="btn btn-secondary" onClick={handleStop} disabled={busy}>Остановить</button>
          )}
        </div>
      </div>

      <h2>Backbone-диалог (чистый обход)</h2>
      <div className="card" style={{ marginBottom: "var(--space-5)" }}>
        {nodes.length === 0 && <p style={{ color: "var(--color-text-muted)" }}>Ходов пока нет.</p>}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {nodes.map((n) => (
            <div key={n.id} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div
                style={{
                  alignSelf: "flex-start",
                  maxWidth: "70%",
                  background: "var(--background-generic)",
                  borderRadius: "var(--radius-m)",
                  padding: "0.8rem 1.2rem",
                  fontSize: 13,
                }}
              >
                <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 2 }}>
                  ход {n.turn_index} · interactor
                </div>
                {n.message_sent}
              </div>
              <div
                style={{
                  alignSelf: "flex-end",
                  maxWidth: "70%",
                  background: "var(--brand-150)",
                  borderRadius: "var(--radius-m)",
                  padding: "0.8rem 1.2rem",
                  fontSize: 13,
                }}
              >
                <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 2 }}>agent</div>
                {n.agent_reply}
              </div>
            </div>
          ))}
        </div>
      </div>

      <h2>Чекпоинты</h2>
      {checkpoints.length === 0 && (
        <div className="card"><p style={{ color: "var(--color-text-muted)" }}>Чекпоинтов пока не найдено.</p></div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
        {checkpoints.map(({ occurrence, attempts }) => (
          <div key={occurrence} className="card">
            <h3 style={{ marginTop: 0 }}>
              Чекпоинт #{occurrence} — <code>{attempts[0]?.tool_name || "?"}</code>
            </h3>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {attempts.map((a) => (
                <div
                  key={a.id}
                  style={{
                    border: "0.1rem solid var(--separator-list)",
                    borderRadius: "var(--radius-m)",
                    padding: "0.8rem 1.2rem",
                  }}
                >
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", fontSize: 13 }}>
                    <strong>попытка {a.attempt_index}</strong>
                    <span className="badge badge-neutral">{stoppedReasonLabel[a.stopped_reason] ?? a.stopped_reason}</span>
                    <span className={`badge ${a.success ? "badge-danger" : "badge-neutral"}`}>
                      {a.success ? "успех" : "не удалось"}
                    </span>
                    {a.diverged_from_backbone && <span className="badge badge-warning">отличается от backbone</span>}
                    <span style={{ color: "var(--color-text-muted)" }}>judge: {a.judge_score.toFixed(2)}</span>
                  </div>
                  {a.divergence_detail && (
                    <p style={{ fontSize: 12, color: "var(--color-text-muted)", margin: "0.4rem 0 0" }}>
                      {a.divergence_detail}
                    </p>
                  )}
                  <details style={{ marginTop: "0.6rem" }}>
                    <summary style={{ cursor: "pointer", fontSize: 12 }}>
                      Ход диалога попытки ({a.trajectory.length})
                    </summary>
                    <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 8 }}>
                      {a.trajectory.map((turn, i) => (
                        <div key={i} style={{ fontSize: 12 }}>
                          <div><strong>ход {turn.turn_index} →</strong> {turn.message_sent}</div>
                          <div style={{ color: "var(--color-text-muted)" }}>← {turn.reply}</div>
                        </div>
                      ))}
                    </div>
                  </details>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
