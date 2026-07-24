import type { TrafficEvent } from "../api/types";

interface DetectionDetail {
  indicator_match?: string | null;
  vuln_signatures?: { class: string; field: string; tool?: string; snippet: string }[];
}

function parseDetail(detail: string): DetectionDetail | null {
  if (!detail) return null;
  try {
    const parsed = JSON.parse(detail);
    if (parsed && typeof parsed === "object") return parsed as DetectionDetail;
    return null;
  } catch {
    return null;
  }
}

function Excerpt({ text }: { text: string }) {
  if (!text) return null;
  return (
    <details>
      <summary style={{ cursor: "pointer", fontSize: 12, color: "var(--color-text-muted)" }}>
        тело ({text.length} симв.)
      </summary>
      <pre
        style={{
          fontSize: 11,
          background: "var(--background-generic)",
          borderRadius: "var(--radius-s)",
          padding: "0.8rem",
          overflowX: "auto",
          marginTop: 6,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {text}
      </pre>
    </details>
  );
}

function DetectionChips({ detail }: { detail: string }) {
  const parsed = parseDetail(detail);
  if (!parsed) return null;
  const hasContent = parsed.indicator_match || (parsed.vuln_signatures && parsed.vuln_signatures.length > 0);
  if (!hasContent) return null;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
      {parsed.indicator_match && (
        <span className="badge badge-danger" title={parsed.indicator_match}>
          индикатор: {parsed.indicator_match}
        </span>
      )}
      {(parsed.vuln_signatures ?? []).map((finding, i) => (
        <span key={i} className="badge badge-danger" title={finding.snippet}>
          {finding.class}{finding.tool ? ` · ${finding.tool}` : ""}
        </span>
      ))}
    </div>
  );
}

interface Flow {
  flowId: string;
  request?: TrafficEvent;
  response?: TrafficEvent;
  timestamp: string;
}

function groupByFlow(events: TrafficEvent[]): Flow[] {
  const byFlow = new Map<string, Flow>();
  for (const e of events) {
    const existing = byFlow.get(e.flow_id) ?? { flowId: e.flow_id, timestamp: e.created_at };
    if (e.direction === "request") existing.request = e;
    else existing.response = e;
    if (e.created_at < existing.timestamp) existing.timestamp = e.created_at;
    byFlow.set(e.flow_id, existing);
  }
  return Array.from(byFlow.values()).sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1));
}

export function FlowTimeline({ events }: { events: TrafficEvent[] }) {
  const flows = groupByFlow(events);

  if (flows.length === 0) {
    return (
      <div className="card" style={{ color: "var(--color-text-muted)" }}>
        Трафик ещё не поступал.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {flows.map((flow) => {
        const injected = flow.request?.injected;
        const success = flow.response?.success_detected;
        return (
          <div
            key={flow.flowId}
            className="card"
            style={{
              borderLeft: success
                ? "0.4rem solid var(--status-negative)"
                : injected
                ? "0.4rem solid var(--brand)"
                : undefined,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
              <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                {new Date(flow.timestamp).toLocaleTimeString()}
              </span>
              <code style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{flow.flowId.slice(0, 8)}</code>
              {injected ? (
                <span className="badge badge-warning">инъекция → {flow.request?.injection_target}</span>
              ) : (
                <span className="badge badge-neutral">без инъекции</span>
              )}
              {success ? (
                <span className="badge badge-danger">инъекция успешна</span>
              ) : (
                <span className="badge badge-success">без успеха</span>
              )}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-700)", marginBottom: 4 }}>Запрос</div>
                {flow.request ? (
                  <Excerpt text={flow.request.raw_excerpt} />
                ) : (
                  <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>—</span>
                )}
              </div>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-700)", marginBottom: 4 }}>Ответ</div>
                {flow.response ? (
                  <>
                    <Excerpt text={flow.response.raw_excerpt} />
                    <DetectionChips detail={flow.response.detail} />
                  </>
                ) : (
                  <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>— (ожидание)</span>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
