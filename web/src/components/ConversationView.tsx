import type { CSSProperties } from "react";
import type { TrafficEvent } from "../api/types";

interface ToolCall {
  id?: string;
  function?: { name?: string; arguments?: string };
}

interface Message {
  role?: string;
  content?: string | null;
  tool_calls?: ToolCall[];
  tool_call_id?: string;
  [key: string]: unknown;
}

function messagesEqual(a: Message, b: Message): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** Whether `longer` is `shorter` plus more messages appended -- i.e. `longer`
 * is a later snapshot of the exact same growing conversation.
 */
function extendsThread(shorter: Message[], longer: Message[]): boolean {
  if (shorter.length > longer.length) return false;
  return shorter.every((m, i) => messagesEqual(m, longer[i]));
}

interface Thread {
  messages: Message[];
  lastCreatedAt: string;
}

/** Re-groups request events into distinct conversation threads. More than
 * one interactor run can share a session_id (re-running "Запустить диалог",
 * or two runs overlapping in time), so the raw request-event stream can
 * interleave two or more unrelated, independently-growing conversations.
 * Each request event's `messages` array either extends an already-known
 * thread (same conversation, later snapshot) or starts a new one -- picking
 * by "most recent timestamp" without this grouping flips between threads
 * and makes turns look like they randomly vanish.
 */
function reconstructThreads(events: TrafficEvent[]): Thread[] {
  const requests = events
    .filter((e) => e.direction === "request")
    .slice()
    .sort((a, b) => (a.created_at < b.created_at ? -1 : 1));

  const threads: Thread[] = [];
  for (const req of requests) {
    let messages: Message[];
    try {
      const body = JSON.parse(req.raw_excerpt);
      messages = Array.isArray(body.messages) ? body.messages : [];
    } catch {
      continue;
    }
    const thread = threads.find((t) => extendsThread(t.messages, messages));
    if (thread) {
      thread.messages = messages;
      thread.lastCreatedAt = req.created_at;
    } else {
      threads.push({ messages, lastCreatedAt: req.created_at });
    }
  }
  return threads;
}

/** Always shows whichever reconstructed thread most recently posted a new
 * message -- i.e. the dialogue actually in progress (or last one to run) --
 * never a stale snapshot from an unrelated interleaved run.
 */
function latestConversationMessages(events: TrafficEvent[]): Message[] {
  const threads = reconstructThreads(events);
  if (threads.length === 0) return [];
  threads.sort((a, b) => (a.lastCreatedAt < b.lastCreatedAt ? 1 : -1));
  return threads[0].messages;
}

/** id -> name for every tool_call seen so far in the conversation, so a
 * later `role: "tool"` message (which only carries `tool_call_id`) can be
 * labeled with the tool it's actually a result of.
 */
function toolNamesById(messages: Message[]): Map<string, string> {
  const names = new Map<string, string>();
  for (const m of messages) {
    if (m.role === "assistant") {
      for (const tc of m.tool_calls ?? []) {
        if (tc.id) names.set(tc.id, tc.function?.name ?? "");
      }
    }
  }
  return names;
}

function RawToggle({ value }: { value: unknown }) {
  return (
    <details style={{ marginTop: 4 }}>
      <summary style={{ cursor: "pointer", fontSize: 11, color: "var(--text-600)" }}>сырые данные</summary>
      <pre
        style={{
          fontSize: 11,
          background: "var(--background-generic)",
          borderRadius: "var(--radius-s)",
          padding: "0.6rem",
          overflowX: "auto",
          marginTop: 4,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

const bubbleBase: CSSProperties = {
  maxWidth: "80%",
  borderRadius: "var(--radius-m)",
  padding: "0.8rem 1.2rem",
  fontSize: 13,
};

export function ConversationView({ events }: { events: TrafficEvent[] }) {
  const messages = latestConversationMessages(events);
  const toolNames = toolNamesById(messages);

  const visible = messages.filter((m) => m.role !== "system");
  if (visible.length === 0) {
    return <p style={{ color: "var(--text-600)", fontSize: 13 }}>Диалог ещё не начался.</p>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {visible.map((m, i) => {
        if (m.role === "tool") {
          const name = m.tool_call_id ? toolNames.get(m.tool_call_id) : undefined;
          const content = typeof m.content === "string" ? m.content : JSON.stringify(m.content);
          return (
            <div
              key={i}
              style={{
                ...bubbleBase,
                alignSelf: "center",
                background: "var(--background-generic)",
                fontFamily: "monospace",
                border: "0.1rem dashed var(--separator-list)",
              }}
            >
              <div style={{ fontSize: 11, color: "var(--text-600)", marginBottom: 2 }}>
                🔧 результат{name ? ` — ${name}` : ""}
              </div>
              <details>
                <summary style={{ cursor: "pointer", fontSize: 12 }}>{content.length} симв. — раскрыть</summary>
                <div style={{ marginTop: 4, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{content}</div>
              </details>
              <RawToggle value={m} />
            </div>
          );
        }

        const isAssistant = m.role === "assistant";
        return (
          <div
            key={i}
            style={{
              ...bubbleBase,
              alignSelf: isAssistant ? "flex-end" : "flex-start",
              background: isAssistant ? "var(--brand-150)" : "var(--background-generic)",
            }}
          >
            <div style={{ fontSize: 11, color: "var(--text-600)", marginBottom: 2 }}>{m.role}</div>
            {m.content && <div>{m.content}</div>}
            {(m.tool_calls ?? []).map((tc, j) => (
              <div key={j} style={{ fontSize: 12, marginTop: m.content ? 6 : 0 }}>
                <span className="badge badge-warning">
                  🔧 {tc.function?.name}({tc.function?.arguments ?? ""})
                </span>
              </div>
            ))}
            <RawToggle value={m} />
          </div>
        );
      })}
    </div>
  );
}
