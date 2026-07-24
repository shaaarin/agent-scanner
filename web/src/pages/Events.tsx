import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { TrafficEvent } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { EventTable } from "../components/EventTable";

const POLL_MS = 3000;

export function Events() {
  const [events, setEvents] = useState<TrafficEvent[]>([]);
  const [sessionFilter, setSessionFilter] = useState("");

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

  return (
    <div>
      <PageHeader
        title="События"
        description="Все запросы и ответы, перехваченные прокси. Обновляется автоматически."
      />
      <div className="field" style={{ maxWidth: 320 }}>
        <label>Фильтр по ID сессии</label>
        <input
          value={sessionFilter}
          onChange={(e) => setSessionFilter(e.target.value)}
          placeholder="например: demo-session-1"
        />
      </div>
      <EventTable events={events} />
    </div>
  );
}
