import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { TrafficEvent, TrafficEventDetail, TrafficEventDetailResponse } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { EventTable } from "../components/EventTable";

const POLL_MS = 3000;

function prettyBody(raw: string): string {
  if (!raw) return "(пусто)";
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

function directionTitle(direction: TrafficEvent["direction"]): string {
  return direction === "request" ? "Запрос к LLM" : "Ответ LLM";
}

function EventBody({ event }: { event: TrafficEventDetail }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.8rem", marginBottom: "0.8rem" }}>
        <span className={`badge ${event.direction === "request" ? "badge-neutral" : "badge-warning"}`}>
          {directionTitle(event.direction)}
        </span>
        <span style={{ fontSize: 12, color: "var(--text-400)" }}>
          {new Date(event.created_at).toLocaleTimeString()}
        </span>
      </div>
      <pre
        style={{
          margin: 0,
          background: "var(--background-generic)",
          borderRadius: "var(--radius-m)",
          padding: "1.2rem",
          fontSize: 12,
          lineHeight: 1.5,
          maxHeight: "48vh",
          overflow: "auto",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {prettyBody(event.raw_excerpt)}
      </pre>
    </div>
  );
}

function EventDetailModal({
  detail,
  onClose,
}: {
  detail: TrafficEventDetailResponse;
  onClose: () => void;
}) {
  const parts = [detail.event, detail.pair]
    .filter((e): e is TrafficEventDetail => Boolean(e))
    .sort((a, b) => (a.direction === b.direction ? a.id - b.id : a.direction === "request" ? -1 : 1));

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
        padding: "2rem",
      }}
      onClick={onClose}
    >
      <div
        className="card"
        style={{ width: "100%", maxWidth: 960, maxHeight: "90vh", overflow: "auto" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "1.6rem", marginBottom: "1.2rem" }}>
          <div>
            <h2 style={{ margin: "0 0 0.4rem" }}>Обмен с LLM</h2>
            <div style={{ display: "flex", gap: "1.2rem", flexWrap: "wrap", fontSize: 13, color: "var(--text-500)" }}>
              <span>{detail.event.host}{detail.event.path}</span>
              <span>сессия: <code>{detail.event.session_id}</code></span>
              {detail.event.scan_id != null && (
                <span>скан: <Link to={`/scans/${detail.event.scan_id}`}>#{detail.event.scan_id}</Link></span>
              )}
              <span>поток: <code>{detail.event.flow_id.slice(0, 8)}</code></span>
            </div>
          </div>
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Закрыть
          </button>
        </div>

        {parts.length === 1 ? (
          <EventBody event={parts[0]} />
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.6rem" }}>
            {parts.map((part) => (
              <EventBody key={part.id} event={part} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function Events() {
  const [events, setEvents] = useState<TrafficEvent[]>([]);
  const [sessionFilter, setSessionFilter] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<TrafficEventDetailResponse | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      const qs = sessionFilter ? `?session_id=${encodeURIComponent(sessionFilter)}` : "";
      api.get<TrafficEvent[]>(`/events${qs}`).then((data) => {
        if (!cancelled) setEvents(data);
      });
    };
    load();
    const interval = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [sessionFilter]);

  const handleSelect = (event: TrafficEvent) => {
    setSelectedId(event.id);
    setLoadingDetail(true);
    setDetail(null);
    api
      .get<TrafficEventDetailResponse>(`/events/${event.id}`)
      .then(setDetail)
      .catch((e) => console.error("Failed to load event:", e))
      .finally(() => setLoadingDetail(false));
  };

  return (
    <div>
      <PageHeader
        title="События"
        description="Запросы и ответы агента, перехваченные прокси. Нажмите на строку, чтобы посмотреть тело."
      />
      <div className="field" style={{ maxWidth: 320 }}>
        <label>Фильтр по сессии</label>
        <input
          value={sessionFilter}
          onChange={(e) => setSessionFilter(e.target.value)}
          placeholder="ID сессии"
        />
      </div>
      <EventTable events={events} selectedId={selectedId} onSelect={handleSelect} />

      {loadingDetail && (
        <div className="card" style={{ marginTop: "1.6rem", color: "var(--text-500)" }}>Загрузка события…</div>
      )}
      {detail && <EventDetailModal detail={detail} onClose={() => { setDetail(null); setSelectedId(null); }} />}
    </div>
  );
}
