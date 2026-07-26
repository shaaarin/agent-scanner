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
  no_success: "успеха нет",
};

function responseText(response: Record<string, unknown>): string {
  const choices = response.choices as { message?: { content?: string } }[] | undefined;
  return choices?.[0]?.message?.content ?? "";
}

function responseToolCalls(response: Record<string, unknown>): string[] {
  const choices = response.choices as { message?: { tool_calls?: { function?: { name?: string } }[] } }[] | undefined;
  const toolCalls = choices?.[0]?.message?.tool_calls ?? [];
  return toolCalls.map((tc) => tc.function?.name ?? "").filter(Boolean);
}

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
    return <div style={{ padding: "2.4rem", color: "var(--text-500)" }}>Загрузка…</div>;
  }

  return (
    <div>
      <PageHeader
        title={treeRun.name}
        description={campaign ? `сканирование: ${campaign.name} (${campaign.session_id})` : undefined}
        actions={
          <Link to={`/campaigns/${treeRun.base_campaign_id}`} className="btn btn-secondary">← К сканированию</Link>
        }
      />

      {error && (
        <div className="card" style={{ borderColor: "var(--status-negative)", marginBottom: "1.6rem" }}>
          {error}
        </div>
      )}

      <div className="card" style={{ marginBottom: "2.4rem" }}>
        <p style={{ fontSize: 13 }}>
          статус: <span className={`badge ${statusBadgeClass[treeRun.status] ?? "badge-neutral"}`}>
            {statusLabel[treeRun.status] ?? treeRun.status}
          </span>
          {" · "}базовый диалог: {nodes.length ? "выполнен" : "не выполнен"}
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

      <h2>Базовый диалог (без инъекций)</h2>
      <div className="card" style={{ marginBottom: "2.4rem" }}>
        {nodes.length === 0 && <p style={{ color: "var(--text-600)" }}>Ходов пока нет.</p>}
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
                <div style={{ fontSize: 11, color: "var(--text-600)", marginBottom: 2 }}>
                  ход {n.turn_index} · пользователь
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
                <div style={{ fontSize: 11, color: "var(--text-600)", marginBottom: 2 }}>агент</div>
                {n.agent_reply}
              </div>
            </div>
          ))}
        </div>
      </div>

      <h2>Чекпоинты</h2>
      {checkpoints.length === 0 && (
        <div className="card"><p style={{ color: "var(--text-600)" }}>Чекпоинтов пока не найдено.</p></div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: "1.6rem" }}>
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
                    {a.diverged_from_backbone && <span className="badge badge-warning">отличается от базового диалога</span>}
                    <span style={{ color: "var(--text-600)" }}>судья: {a.judge_score.toFixed(2)}</span>
                  </div>
                  {a.divergence_detail && (
                    <p style={{ fontSize: 12, color: "var(--text-600)", margin: "0.4rem 0 0" }}>
                      {a.divergence_detail}
                    </p>
                  )}
                  <details style={{ marginTop: "0.6rem" }}>
                    <summary style={{ cursor: "pointer", fontSize: 12 }}>
                      Прямой вызов LLM с изменённым результатом инструмента
                    </summary>
                    <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
                      {a.trajectory.map((turn, i) => (
                        <div key={i} style={{ fontSize: 12 }}>
                          <div><strong>ответ модели:</strong> {responseText(turn.response) || "(пусто)"}</div>
                          {responseToolCalls(turn.response).length > 0 && (
                            <div style={{ color: "var(--text-600)" }}>
                              вызовы инструментов: {responseToolCalls(turn.response).join(", ")}
                            </div>
                          )}
                          <details style={{ marginTop: 4 }}>
                            <summary style={{ cursor: "pointer" }}>сырые данные запроса/ответа</summary>
                            <pre style={{ fontSize: 11, overflow: "auto", maxHeight: 240 }}>{JSON.stringify(turn, null, 2)}</pre>
                          </details>
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
