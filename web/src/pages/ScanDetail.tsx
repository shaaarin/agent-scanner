import { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, launcherApi, interactorApi, generatorApi } from "../api/client";
import type {
  AgentConfig,
  Campaign,
  FuzzRun,
  InteractorRun,
  LaunchStatus,
  TrafficEvent,
  TreeRun,
} from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { FlowTimeline } from "../components/FlowTimeline";
import { ConversationView } from "../components/ConversationView";

const EVENTS_POLL_MS = 3000;
const STATUS_POLL_MS = 4000;

const runStatusLabel: Record<string, string> = {
  pending: "не запущен",
  running: "выполняется",
  paused: "на паузе",
  stopped: "остановлен",
  completed: "завершён",
};

const runStatusBadgeClass: Record<string, string> = {
  running: "badge-warning",
  completed: "badge-success",
  stopped: "badge-danger",
};

// launcher/app/pod_manager.py::pod_status returns "not_launched" (no pod
// recorded yet), "not_found" (recorded but gone from the cluster), or a raw
// k8s phase (Pending/Running/Succeeded/Failed/Unknown) -- collapsed into a
// small state machine so the UI can show/hide the right buttons instead of
// always offering both "Запустить"/"Остановить" regardless of reality.
type AgentPhase = "not_launched" | "building_or_starting" | "running" | "stopped_or_failed";

function agentPhase(status: string | undefined): AgentPhase {
  if (!status || status === "not_launched") return "not_launched";
  if (status === "Pending") return "building_or_starting";
  if (status === "Running") return "running";
  return "stopped_or_failed"; // Succeeded / Failed / not_found / Unknown
}

const agentPhaseLabel: Record<AgentPhase, string> = {
  not_launched: "не запущен",
  building_or_starting: "собирается и запускается…",
  running: "запущен",
  stopped_or_failed: "остановлен или завершился",
};

const agentPhaseBadgeClass: Record<AgentPhase, string> = {
  not_launched: "badge-neutral",
  building_or_starting: "badge-warning",
  running: "badge-success",
  stopped_or_failed: "badge-danger",
};

export function ScanDetail() {
  const { id } = useParams();
  const campaignId = Number(id);

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [agentConfig, setAgentConfig] = useState<AgentConfig | null>(null);
  const [fuzzRun, setFuzzRun] = useState<FuzzRun | null>(null);
  const [treeRun, setTreeRun] = useState<TreeRun | null>(null);
  const [events, setEvents] = useState<TrafficEvent[]>([]);
  const [launchStatus, setLaunchStatus] = useState<LaunchStatus | null>(null);
  const [launching, setLaunching] = useState(false);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<InteractorRun | null>(null);
  const [busyRun, setBusyRun] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.get<Campaign>(`/campaigns/${campaignId}`).then(async (c) => {
      setCampaign(c);
      const [cfg, fuzzRuns, treeRuns] = await Promise.all([
        c.agent_config_id ? api.get<AgentConfig>(`/agent-configs/${c.agent_config_id}`) : Promise.resolve(null),
        api.get<FuzzRun[]>(`/fuzz-runs?base_campaign_id=${c.id}`),
        api.get<TreeRun[]>(`/tree-runs?base_campaign_id=${c.id}`),
      ]);
      setAgentConfig(cfg);
      setFuzzRun(fuzzRuns[0] ?? null);
      setTreeRun(treeRuns[0] ?? null);
    });
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaignId]);

  useEffect(() => {
    if (!campaign) return;
    let cancelled = false;
    const poll = () => {
      api
        .get<TrafficEvent[]>(`/events?session_id=${encodeURIComponent(campaign.session_id)}&limit=200`)
        .then((data) => { if (!cancelled) setEvents(data); });
    };
    poll();
    const interval = setInterval(poll, EVENTS_POLL_MS);
    return () => { cancelled = true; clearInterval(interval); };
  }, [campaign]);

  useEffect(() => {
    if (!campaign || !agentConfig) return;
    let cancelled = false;
    const poll = () => {
      launcherApi
        .get<LaunchStatus>(`/status/${campaignId}`)
        .then((data) => { if (!cancelled) setLaunchStatus(data); })
        .catch(() => { /* лаунчер недоступен */ });
    };
    poll();
    const interval = setInterval(poll, STATUS_POLL_MS);
    return () => { cancelled = true; clearInterval(interval); };
  }, [campaign, agentConfig, campaignId]);

  // Fuzz/tree run status can change from the background generator task even
  // without any action here -- poll them too while either exists.
  useEffect(() => {
    if (!fuzzRun && !treeRun) return;
    let cancelled = false;
    const poll = () => {
      if (fuzzRun) api.get<FuzzRun>(`/fuzz-runs/${fuzzRun.id}`).then((r) => { if (!cancelled) setFuzzRun(r); });
      if (treeRun) api.get<TreeRun>(`/tree-runs/${treeRun.id}`).then((r) => { if (!cancelled) setTreeRun(r); });
    };
    const interval = setInterval(poll, EVENTS_POLL_MS);
    return () => { cancelled = true; clearInterval(interval); };
  }, [fuzzRun?.id, treeRun?.id]);

  const stats = useMemo(() => {
    const requests = events.filter((e) => e.direction === "request");
    const responses = events.filter((e) => e.direction === "response");
    return { total: requests.length, successes: responses.filter((e) => e.success_detected).length };
  }, [events]);

  async function handleLaunch() {
    setError(null);
    setLaunching(true);
    try {
      const status = await launcherApi.post<LaunchStatus>("/launch", { campaign_id: campaignId });
      setLaunchStatus(status);
    } catch (e) {
      setError(String(e));
    } finally {
      setLaunching(false);
    }
  }

  async function handleStop() {
    setError(null);
    try {
      await launcherApi.post(`/stop/${campaignId}`, {});
      setLaunchStatus({ status: "not_launched" });
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleRunInteractor() {
    setError(null);
    setRunning(true);
    setRunResult(null);
    try {
      const result = await interactorApi.post<InteractorRun>("/run", { campaign_id: campaignId, max_turns: 5 });
      setRunResult(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }

  async function handleStartRun(kind: "fuzz" | "tree", runId: number) {
    setError(null);
    setBusyRun(true);
    try {
      await generatorApi.post(`/${kind}/${runId}/start`, {});
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyRun(false);
    }
  }

  async function handleStopRun(kind: "fuzz" | "tree", runId: number) {
    setError(null);
    setBusyRun(true);
    try {
      await generatorApi.post(`/${kind}/${runId}/stop`, {});
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyRun(false);
    }
  }

  if (!campaign) {
    return <div style={{ padding: "2.4rem", color: "var(--text-500)" }}>Загрузка…</div>;
  }

  const needsInteractor = agentConfig && agentConfig.interaction_mode !== "none";
  const phase = agentPhase(launchStatus?.status);

  return (
    <div>
      <PageHeader
        title={campaign.name}
        description={`сессия ${campaign.session_id}`}
        actions={<Link to="/campaigns" className="btn btn-secondary">← К сканированиям</Link>}
      />

      {error && (
        <div className="card" style={{ borderColor: "var(--status-negative)", marginBottom: "1.6rem" }}>
          {error}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "1.6rem", marginBottom: "2.4rem" }}>
        <div className="card stat-card">
          <div className="stat-label">Обменов с агентом</div>
          <div className="stat-value">{stats.total}</div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">Успешных атак замечено в трафике</div>
          <div className="stat-value danger">{stats.successes}</div>
        </div>
      </div>

      {agentConfig && (
        <div className="card" style={{ marginBottom: "2.4rem" }}>
          <h3>Целевой агент — {agentConfig.name}</h3>
          <p style={{ fontSize: 13 }}>
            <span className={`badge ${agentPhaseBadgeClass[phase]}`}>{agentPhaseLabel[phase]}</span>
            {launchStatus?.pod_name && <> · pod <code>{launchStatus.pod_name}</code></>}
            {launchStatus?.built_image && <> · образ <code style={{ fontSize: 11 }}>{launchStatus.built_image}</code></>}
          </p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {(phase === "not_launched" || phase === "stopped_or_failed") && (
              <button className="btn" onClick={handleLaunch} disabled={launching}>
                {launching ? "Запуск (сборка образа, может занять время)…" : "Запустить агент"}
              </button>
            )}
            {phase === "building_or_starting" && (
              <button className="btn" disabled>Собирается и запускается…</button>
            )}
            {phase !== "not_launched" && (
              <button className="btn btn-secondary" onClick={handleStop}>Остановить</button>
            )}
            {needsInteractor && (
              <button className="btn" onClick={handleRunInteractor} disabled={running}>
                {running ? "Выполнение…" : "Запустить интерактор"}
              </button>
            )}
          </div>

          {needsInteractor && (
            <div style={{ marginTop: "1.6rem" }}>
              <h3>
                Диалог{" "}
                {runResult && (
                  <span className={`badge ${runResult.success_detected ? "badge-danger" : "badge-success"}`}>
                    {runResult.success_detected ? "инъекция успешна" : `${runResult.turns} ходов, без успеха`}
                  </span>
                )}
              </h3>
              <p style={{ fontSize: 12, color: "var(--text-600)", margin: "0 0 0.8rem" }}>
                Восстановлено из перехваченного proxy трафика — обновляется по мере поступления
                новых событий, включая вызовы инструментов. Полные сырые запросы/ответы — в
                таймлайне трафика ниже.
              </p>
              <ConversationView events={events} />
            </div>
          )}
        </div>
      )}

      <h2>Фаззинг</h2>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.6rem", marginBottom: "2.4rem" }}>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Прямая инъекция (в сообщении пользователя)</h3>
          {fuzzRun ? (
            <>
              <p style={{ fontSize: 13 }}>
                <span className={`badge ${runStatusBadgeClass[fuzzRun.status] ?? "badge-neutral"}`}>
                  {runStatusLabel[fuzzRun.status] ?? fuzzRun.status}
                </span>
                {" · "}макс. итераций: {fuzzRun.max_iterations}
              </p>
              <div style={{ display: "flex", gap: 8 }}>
                {(fuzzRun.status === "pending" || fuzzRun.status === "paused") && (
                  <button className="btn btn-secondary" disabled={busyRun} onClick={() => handleStartRun("fuzz", fuzzRun.id)}>Запустить</button>
                )}
                {fuzzRun.status === "running" && (
                  <button className="btn btn-secondary" disabled={busyRun} onClick={() => handleStopRun("fuzz", fuzzRun.id)}>Остановить</button>
                )}
                <Link to={`/fuzz-runs/${fuzzRun.id}`} className="btn btn-secondary">Подробнее →</Link>
              </div>
            </>
          ) : (
            <p style={{ color: "var(--text-600)", fontSize: 13 }}>
              Не настроен. Включите на странице <Link to="/campaigns">сканирования</Link> (изменить → «Прямая инъекция»).
            </p>
          )}
        </div>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Индирект-инъекция (в результате инструмента)</h3>
          {treeRun ? (
            <>
              <p style={{ fontSize: 13 }}>
                <span className={`badge ${runStatusBadgeClass[treeRun.status] ?? "badge-neutral"}`}>
                  {runStatusLabel[treeRun.status] ?? treeRun.status}
                </span>
                {" · "}попыток/чекпоинт: {treeRun.attempts_per_checkpoint}
              </p>
              <div style={{ display: "flex", gap: 8 }}>
                {(treeRun.status === "pending" || treeRun.status === "paused") && (
                  <button className="btn btn-secondary" disabled={busyRun} onClick={() => handleStartRun("tree", treeRun.id)}>Запустить</button>
                )}
                {treeRun.status === "running" && (
                  <button className="btn btn-secondary" disabled={busyRun} onClick={() => handleStopRun("tree", treeRun.id)}>Остановить</button>
                )}
                <Link to={`/tree-runs/${treeRun.id}`} className="btn btn-secondary">Подробнее →</Link>
              </div>
            </>
          ) : (
            <p style={{ color: "var(--text-600)", fontSize: 13 }}>
              Не настроен. Включите на странице <Link to="/campaigns">сканирования</Link> (изменить → «Индирект-инъекция»).
            </p>
          )}
        </div>
      </div>

      <h2>Таймлайн трафика</h2>
      <FlowTimeline events={events} />
    </div>
  );
}
