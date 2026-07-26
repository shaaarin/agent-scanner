import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { TrafficEvent } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { EventTable } from "../components/EventTable";

export function Findings() {
  const [events, setEvents] = useState<TrafficEvent[]>([]);

  useEffect(() => {
    api.get<TrafficEvent[]>("/events?success_detected=true").then(setEvents);
  }, []);

  const bySession = events.reduce<Record<string, TrafficEvent[]>>((acc, e) => {
    (acc[e.session_id] ??= []).push(e);
    return acc;
  }, {});

  const sessionCount = Object.keys(bySession).length;

  return (
    <div>
      <PageHeader
        title="Уязвимости"
        description="Обмены с зафиксированной успешной инъекцией, сгруппированные по сессии."
      />
      {sessionCount === 0 && (
        <div className="card" style={{ color: "var(--text-600)" }}>
          Уязвимостей не обнаружено.
        </div>
      )}
      {Object.entries(bySession).map(([sessionId, sessionEvents]) => (
        <div key={sessionId} style={{ marginBottom: "2.4rem" }}>
          <h2>
            {sessionId}{" "}
            <span className="badge badge-danger">
              {sessionEvents.length}{" "}
              {sessionEvents.length === 1 ? "уязвимость" : sessionEvents.length < 5 ? "уязвимости" : "уязвимостей"}
            </span>
          </h2>
          <EventTable events={sessionEvents} />
        </div>
      ))}
    </div>
  );
}
