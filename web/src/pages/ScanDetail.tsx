import { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, launcherApi, interactorApi } from "../api/client";
import type {
  AgentConfig,
  Campaign,
  InjectionTemplate,
  InteractorRun,
  LaunchStatus,
  TrafficEvent,
} from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { FlowTimeline } from "../components/FlowTimeline";

const EVENTS_POLL_MS = 3000;
const STATUS_POLL_MS = 4000;

export function ScanDetail() {
  const { id } = useParams();
  const campaignId = Number(id);

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [template, setTemplate] = useState<InjectionTemplate | null>(null);
  const [agentConfig, setAgentConfig] = useState<AgentConfig | null>(null);
  const [events, setEvents] = useState<TrafficEvent[]>([]);
  const [launchStatus, setLaunchStatus] = useState<LaunchStatus | null>(null);
  const [launching, setLaunching] = useState(false);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<InteractorRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<Campaign>(`/campaigns/${campaignId}`).then(async (c) => {
      setCampaign(c);
      const [tpl, cfg] = await Promise.all([
        api.get<InjectionTemplate>(`/templates/${c.template_id}`),
        c.agent_config_id ? api.get<AgentConfig>(`/agent-configs/${c.agent_config_id}`) : Promise.resolve(null),
      ]);
      setTemplate(tpl);
      setAgentConfig(cfg);
    });
  }, [campaignId]);

  useEffect(() => {
    if (!campaign) return;
    let cancelled = false;
    const load = () => {
      api
        .get<TrafficEvent[]>(`/events?session_id=${encodeURIComponent(campaign.session_id)}&limit=200`)
        .then((data) => { if (!cancelled) setEvents(data); });
    };
    load();
    const interval = setInterval(load, EVENTS_POLL_MS);
    return () => { cancelled = true; clearInterval(interval); };
  }, [campaign]);

  useEffect(() => {
    if (!campaign || !agentConfig) return;
    let cancelled = false;
    const load = () => {
      launcherApi
        .get<LaunchStatus>(`/status/${campaignId}`)
        .then((data) => { if (!cancelled) setLaunchStatus(data); })
        .catch(() => { /* лаунчер недоступен */ });
    };
    load();
    const interval = setInterval(load, STATUS_POLL_MS);
    return () => { cancelled = true; clearInterval(interval); };
  }, [campaign, agentConfig, campaignId]);

  const stats = useMemo(() => {
    const requests = events.filter((e) => e.direction === "request");
    const responses = events.filter((e) => e.direction === "response");
    const injected = requests.filter((e) => e.injected).length;
    const successes = responses.filter((e) => e.success_detected).length;
    return { total: requests.length, injected, successes };
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

  if (!campaign) {
    return <div style={{ padding: "var(--space-5)", color: "var(--text-500)" }}>Загрузка…</div>;
  }

  const needsInteractor = agentConfig && agentConfig.interaction_mode !== "none";

  return (
    <div>
      <PageHeader
        title={campaign.name}
        description={`сессия ${campaign.session_id} · шаблон: ${template?.name ?? campaign.template_id}`}
        actions={<Link to="/campaigns" className="btn btn-secondary">← К сканированиям</Link>}
      />

      {error && (
        <div className="card" style={{ borderColor: "var(--color-danger)", marginBottom: "var(--space-4)" }}>
          {error}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "var(--space-4)", marginBottom: "var(--space-5)" }}>
        <div className="card stat-card">
          <div className="stat-label">Обменов</div>
          <div className="stat-value">{stats.total}</div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">С инъекцией</div>
          <div className="stat-value accent">{stats.injected}</div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">Успешных атак</div>
          <div className="stat-value danger">{stats.successes}</div>
        </div>
      </div>

      {agentConfig && (
        <div className="card" style={{ marginBottom: "var(--space-5)" }}>
          <h3>Целевой агент — {agentConfig.name}</h3>
          <p style={{ fontSize: 13 }}>
            {launchStatus ? (
              <>
                статус: <span className="badge badge-neutral">{launchStatus.status}</span>
                {launchStatus.pod_name && <> · pod <code>{launchStatus.pod_name}</code></>}
                {launchStatus.built_image && <> · образ <code style={{ fontSize: 11 }}>{launchStatus.built_image}</code></>}
              </>
            ) : (
              "статус неизвестен"
            )}
          </p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button className="btn" onClick={handleLaunch} disabled={launching}>
              {launching ? "Запуск (сборка образа, может занять время)…" : "Запустить агент"}
            </button>
            <button className="btn btn-secondary" onClick={handleStop}>Остановить</button>
            {needsInteractor && (
              <button className="btn" onClick={handleRunInteractor} disabled={running}>
                {running ? "Выполнение…" : "Запустить интерактор"}
              </button>
            )}
          </div>

          {runResult && (
            <div style={{ marginTop: "var(--space-4)" }}>
              <h3>
                Транскрипт{" "}
                {runResult.success_detected && <span className="badge badge-danger">инъекция успешна</span>}
              </h3>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {runResult.transcript.map((turn, i) => (
                  <div
                    key={i}
                    style={{
                      alignSelf: turn.speaker === "interactor" ? "flex-start" : "flex-end",
                      maxWidth: "70%",
                      background:
                        turn.speaker === "interactor" ? "var(--background-generic)" : "var(--brand-150)",
                      borderRadius: "var(--radius-m)",
                      padding: "0.8rem 1.2rem",
                      fontSize: 13,
                    }}
                  >
                    <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 2 }}>
                      {turn.speaker}
                    </div>
                    {turn.text}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <h2>Таймлайн инъекций</h2>
      <FlowTimeline events={events} />
    </div>
  );
}
