import { Link } from "react-router-dom";
import type { TrafficEvent } from "../api/types";

const directionLabel: Record<string, string> = {
  request: "запрос",
  response: "ответ",
};

export function EventTable({
  events,
  selectedId,
  onSelect,
}: {
  events: TrafficEvent[];
  selectedId?: number | null;
  onSelect?: (event: TrafficEvent) => void;
}) {
  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      <table>
        <thead>
          <tr>
            <th>Время</th>
            <th>Сессия</th>
            <th>Скан</th>
            <th>Направление</th>
            <th>Провайдер</th>
            <th>Хост</th>
            <th>Путь</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr
              key={e.id}
              onClick={() => onSelect?.(e)}
              style={{
                cursor: onSelect ? "pointer" : undefined,
                background: e.id === selectedId ? "var(--background-generic)" : undefined,
              }}
            >
              <td style={{ fontSize: 12, color: "var(--text-600)", whiteSpace: "nowrap" }}>
                {new Date(e.created_at).toLocaleTimeString()}
              </td>
              <td><code>{e.session_id}</code></td>
              <td>
                {e.scan_id != null ? (
                  <Link to={`/scans/${e.scan_id}`} onClick={(ev) => ev.stopPropagation()}>
                    #{e.scan_id}
                  </Link>
                ) : (
                  <span style={{ color: "var(--text-600)" }}>—</span>
                )}
              </td>
              <td>
                <span className={`badge ${e.direction === "request" ? "badge-neutral" : "badge-warning"}`}>
                  {directionLabel[e.direction] ?? e.direction}
                </span>
              </td>
              <td>{e.provider}</td>
              <td><code>{e.host}</code></td>
              <td style={{ fontSize: 12, color: "var(--text-600)" }}>{e.path}</td>
            </tr>
          ))}
          {events.length === 0 && (
            <tr>
              <td colSpan={7} style={{ color: "var(--text-500)", padding: "2.4rem", textAlign: "center" }}>
                События появятся здесь, когда агент начнёт обращаться к LLM.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
