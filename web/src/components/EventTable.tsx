import type { TrafficEvent } from "../api/types";

const directionLabel: Record<string, string> = {
  request: "запрос",
  response: "ответ",
};

export function EventTable({ events }: { events: TrafficEvent[] }) {
  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      <table>
        <thead>
          <tr>
            <th>Время</th>
            <th>Сессия</th>
            <th>Направление</th>
            <th>Инъекция</th>
            <th>Цель</th>
            <th>Успех</th>
            <th>Детали</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id}>
              <td style={{ fontSize: 12, color: "var(--text-600)", whiteSpace: "nowrap" }}>
                {new Date(e.created_at).toLocaleTimeString()}
              </td>
              <td><code>{e.session_id}</code></td>
              <td>
                <span className={`badge ${e.direction === "request" ? "badge-neutral" : "badge-warning"}`}>
                  {directionLabel[e.direction] ?? e.direction}
                </span>
              </td>
              <td>
                {e.injected
                  ? <span className="badge badge-warning">да</span>
                  : <span className="badge badge-neutral">нет</span>}
              </td>
              <td>{e.injection_target ?? "—"}</td>
              <td>
                {e.success_detected
                  ? <span className="badge badge-danger">успех</span>
                  : <span className="badge badge-neutral">—</span>}
              </td>
              <td style={{ fontSize: 12, color: "var(--text-600)" }}>{e.detail}</td>
            </tr>
          ))}
          {events.length === 0 && (
            <tr>
              <td colSpan={7} style={{ color: "var(--text-600)" }}>Событий нет.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
