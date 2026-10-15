import { Fragment, useState } from "react";
import type {
  SkillsEngineStatus,
  SkillsFinding,
  SkillsScanResults as SkillsScanResultsData,
  SkillsSeverity,
  SkillsSkillResult,
  SkillsSource,
  SkillsSummary,
  SkillsVerdict,
} from "../api/types";
import { SEVERITY_BADGES, SEVERITY_LABELS } from "../api/scanTypes";

// Результаты скана agent_skills (формат -- SKILLSS.md §2.7). Вердикт считает
// платформа (D-52); вердикты движков (`own_verdict`) показываем справочно.

const SEVERITIES: SkillsSeverity[] = ["critical", "high", "medium", "low", "info"];
const SEVERITY_LABEL: Record<SkillsSeverity, string> = { ...SEVERITY_LABELS, info: "Информация" };
const SEVERITY_BADGE: Record<SkillsSeverity, string> = { ...SEVERITY_BADGES, info: "badge-neutral" };

const VERDICT_ORDER: SkillsVerdict[] = ["block", "review", "pass"];
const VERDICTS: Record<SkillsVerdict, { label: string; badge: string; hint: string }> = {
  block: {
    label: "block — блокировать",
    badge: "badge-danger",
    hint:
      "Сработали правила платформы (свои YARA-правила или проверка frontmatter) либо находку уровня critical " +
      "подтвердили оба движка. Не устанавливайте навык, пока не разберёте находки.",
  },
  review: {
    label: "review — нужна ручная проверка",
    badge: "badge-warning",
    hint:
      "Движки нашли проблемы уровня high или critical. Такое бывает и у легитимных навыков со скриптами — " +
      "посмотрите находки и решите вручную.",
  },
  pass: {
    label: "pass — находок high и выше нет",
    badge: "badge-success",
    hint:
      "Это не гарантия безопасности: находки medium и ниже видны в отчёте, а смысловые атаки в тексте " +
      "навыка без LLM-анализа не обнаруживаются.",
  },
};

const ENGINE_STATUSES: Record<SkillsEngineStatus, { label: string; badge: string }> = {
  ok: { label: "Отработал", badge: "badge-success" },
  partial: { label: "Частично", badge: "badge-warning" },
  failed: { label: "Не отработал", badge: "badge-danger" },
  timeout: { label: "Превышено время", badge: "badge-danger" },
};

const REJECT_REASONS: Record<string, string> = {
  zip_slip: "Пути за пределами архива",
  symlink: "Символические ссылки в архиве",
  encrypted: "Зашифрованные файлы в архиве",
  limits: "Превышены лимиты распаковки",
};

const FILTERS: { value: SkillsSeverity; label: string }[] = [
  { value: "info", label: "все" },
  { value: "medium", label: "medium и выше" },
  { value: "high", label: "high и выше" },
];

const muted = { color: "var(--text-600)", fontSize: "var(--font-caption-m-size)" };
const mono = {
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
  fontSize: "var(--font-caption-m-size)",
  wordBreak: "break-all" as const,
};
const blockStyle = {
  padding: "1rem",
  background: "var(--background-generic)",
  borderRadius: "var(--radius-m)",
  whiteSpace: "pre-wrap" as const,
  fontSize: "var(--font-caption-m-size)",
};
const tile = { padding: "1rem", background: "var(--background-generic)", borderRadius: "var(--radius-m)" };

function formatSize(bytes?: number): string | null {
  if (bytes === undefined || bytes === null) return null;
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КиБ`;
  return `${(bytes / 1024 / 1024).toFixed(1)} МиБ`;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} с`;
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)} мин ${total % 60} с`;
}

function sourceLine(source?: SkillsSource): string | null {
  if (!source) return null;
  if (source.kind === "zip") {
    return [
      source.filename ? `архив ${source.filename}` : "архив",
      formatSize(source.size_bytes),
      source.sha256 && `sha256 ${source.sha256.slice(0, 12)}`,
    ]
      .filter(Boolean)
      .join(" · ");
  }
  return [
    source.git_repo_url,
    source.git_ref && `ветка ${source.git_ref}`,
    source.commit && `коммит ${source.commit.slice(0, 12)}`,
  ]
    .filter(Boolean)
    .join(" · ");
}

function location(finding: SkillsFinding): string {
  if (!finding.file) return "—";
  return finding.line ? `${finding.file}:${finding.line}` : finding.file;
}

function SeverityBadge({ severity }: { severity: SkillsSeverity }) {
  return <span className={`badge ${SEVERITY_BADGE[severity] ?? "badge-neutral"}`}>{SEVERITY_LABEL[severity] ?? severity}</span>;
}

function VerdictBadge({ verdict }: { verdict: SkillsVerdict }) {
  return <span className={`badge ${VERDICTS[verdict]?.badge ?? "badge-neutral"}`}>{verdict}</span>;
}

function SummaryLine({ summary }: { summary: SkillsSummary }) {
  const parts = SEVERITIES.filter((severity) => summary[severity]);
  if (!parts.length) return <span style={muted}>находок нет</span>;
  return (
    <span style={{ display: "inline-flex", flexWrap: "wrap", gap: "0.3rem" }}>
      {parts.map((severity) => (
        <span key={severity} className={`badge ${SEVERITY_BADGE[severity]}`}>
          {SEVERITY_LABEL[severity]}: {summary[severity]}
        </span>
      ))}
    </span>
  );
}

function FindingsTable({ findings, engineLabel }: { findings: SkillsFinding[]; engineLabel: (name: string) => string }) {
  const [expanded, setExpanded] = useState<number | null>(null);
  return (
    <table style={{ width: "100%", borderCollapse: "collapse" }}>
      <thead>
        <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
          <th style={{ padding: "1rem 1.2rem", textAlign: "left" }}>Серьёзность</th>
          <th style={{ padding: "1rem 1.2rem", textAlign: "left" }}>Движок</th>
          <th style={{ padding: "1rem 1.2rem", textAlign: "left" }}>Где</th>
          <th style={{ padding: "1rem 1.2rem", textAlign: "left" }}>Находка</th>
        </tr>
      </thead>
      <tbody>
        {findings.map((finding, index) => {
          const isOpen = expanded === index;
          const meta = [
            `правило ${finding.rule_id}`,
            finding.category && `категория ${finding.category}`,
            finding.confidence !== null && finding.confidence !== undefined &&
              `уверенность движка ${Math.round(finding.confidence * 100)}%`,
          ].filter(Boolean);
          return (
            <Fragment key={index}>
              <tr
                onClick={() => setExpanded(isOpen ? null : index)}
                style={{
                  borderBottom: isOpen ? "none" : "0.1rem solid var(--separator-default)",
                  cursor: "pointer",
                  verticalAlign: "top",
                }}
              >
                <td style={{ padding: "1rem 1.2rem", whiteSpace: "nowrap" }}>
                  <SeverityBadge severity={finding.severity} />
                </td>
                <td style={{ padding: "1rem 1.2rem", fontSize: "var(--font-caption-m-size)", whiteSpace: "nowrap" }}>{engineLabel(finding.engine)}</td>
                <td style={{ padding: "1rem 1.2rem", ...mono }}>{location(finding)}</td>
                <td style={{ padding: "1rem 1.2rem", fontSize: "var(--font-caption-m-size)" }}>{finding.title || finding.rule_id}</td>
              </tr>
              {isOpen && (
                <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                  <td colSpan={4} style={{ padding: "0 1.4rem 1.4rem" }}>
                    <p style={{ ...muted, margin: "0 0 0.8rem" }}>{meta.join(" · ")}</p>
                    {finding.finding && (
                      <div style={{ marginBottom: "0.8rem" }}>
                        <div style={{ ...muted, marginBottom: "0.4rem" }}>Описание</div>
                        <div style={blockStyle}>{finding.finding}</div>
                      </div>
                    )}
                    {finding.snippet && (
                      <div style={{ marginBottom: "0.8rem" }}>
                        <div style={{ ...muted, marginBottom: "0.4rem" }}>Фрагмент</div>
                        <pre style={{ ...blockStyle, ...mono, margin: 0, wordBreak: "break-all" }}>{finding.snippet}</pre>
                      </div>
                    )}
                    <div>
                      <div style={{ ...muted, marginBottom: "0.4rem" }}>Рекомендация</div>
                      <div style={blockStyle}>{finding.fix || "Движок не предложил исправление."}</div>
                    </div>
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}

function SkillCard({
  skill,
  minSeverity,
  defaultOpen,
  engineLabel,
}: {
  skill: SkillsSkillResult;
  minSeverity: SkillsSeverity;
  defaultOpen: boolean;
  engineLabel: (name: string) => string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const limit = SEVERITIES.indexOf(minSeverity);
  const findings = skill.findings.filter((finding) => SEVERITIES.indexOf(finding.severity) <= limit);
  const hidden = skill.findings.length - findings.length;
  const engineNotes = Object.entries(skill.engines).flatMap(([name, engine]) => [
    ...(engine.status !== "ok"
      ? [{ name, error: true, text: `${ENGINE_STATUSES[engine.status]?.label ?? engine.status}${engine.error ? `: ${engine.error}` : ""}` }]
      : []),
    ...engine.warnings.map((text) => ({ name, error: false, text })),
  ]);

  return (
    <div style={{ border: "0.1rem solid var(--separator-default)", borderRadius: "var(--radius-m)", marginBottom: "1rem" }}>
      <div
        onClick={() => setOpen(!open)}
        style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0.8rem", padding: "1.2rem 1.4rem", cursor: "pointer" }}
      >
        <span style={{ color: "var(--text-500)", width: "1rem" }}>{open ? "▾" : "▸"}</span>
        <VerdictBadge verdict={skill.verdict} />
        <span style={{ fontWeight: 600 }}>{skill.name}</span>
        {skill.path !== skill.name && <span style={{ ...mono, color: "var(--text-500)" }}>{skill.path}</span>}
        {!skill.complete && <span className="badge badge-warning">проверка неполная</span>}
        <span style={{ marginLeft: "auto" }}>
          <SummaryLine summary={skill.summary} />
        </span>
      </div>

      {open && (
        <div style={{ padding: "0 1.4rem 1.4rem" }}>
          {skill.verdict_reasons.length > 0 && (
            <div style={{ marginBottom: "1rem" }}>
              <div style={{ ...muted, marginBottom: "0.4rem" }}>Почему {skill.verdict}</div>
              <ul style={{ margin: 0, paddingLeft: "1.4rem" }}>
                {skill.verdict_reasons.map((reason, index) => (
                  <li key={index}>{reason}</li>
                ))}
              </ul>
            </div>
          )}

          <p style={{ ...muted, margin: "0 0 1rem" }}>
            {Object.entries(skill.engines)
              .map(([name, engine]) => {
                const own = engine.own_verdict ? `, свой вердикт движка: ${engine.own_verdict}` : "";
                return `${engineLabel(name)} — ${engine.findings} находок, ${formatDuration(engine.duration_sec)}${own}`;
              })
              .join(" · ")}
          </p>

          {engineNotes.map((note, index) => (
            <div
              key={index}
              style={{
                padding: "0.6rem 1rem",
                marginBottom: "0.6rem",
                borderLeft: `0.3rem solid ${note.error ? "var(--status-negative)" : "var(--status-warning)"}`,
                background: "var(--background-generic)",
                fontSize: "var(--font-caption-m-size)",
              }}
            >
              <b>{engineLabel(note.name)}:</b> {note.text}
            </div>
          ))}

          {findings.length > 0 ? (
            <FindingsTable findings={findings} engineLabel={engineLabel} />
          ) : (
            <p style={{ margin: 0, color: "var(--text-700)" }}>
              {skill.findings.length ? "Нет находок выбранного уровня." : "Находок нет."}
            </p>
          )}
          {(hidden > 0 || skill.findings_omitted > 0) && (
            <p style={{ ...muted, margin: "0.8rem 0 0" }}>
              {[
                hidden > 0 && `скрыто фильтром: ${hidden}`,
                skill.findings_omitted > 0 && `не вошло в отчёт из-за лимита: ${skill.findings_omitted}`,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export function SkillsScanResults({ results }: { results: SkillsScanResultsData }) {
  const [minSeverity, setMinSeverity] = useState<SkillsSeverity>("info");
  const verdict = VERDICTS[results.verdict] ?? VERDICTS.review;
  const engines = Object.entries(results.engines ?? {});
  const engineLabel = (name: string) => results.engines?.[name]?.label ?? name;
  const skills = [...(results.skills ?? [])].sort(
    (a, b) => VERDICT_ORDER.indexOf(a.verdict) - VERDICT_ORDER.indexOf(b.verdict) || a.path.localeCompare(b.path),
  );
  const counts = results.verdict_counts;
  const source = sourceLine(results.source);

  return (
    <div className="card" style={{ padding: "2rem" }}>
      <h3 style={{ marginBottom: "0.5rem" }}>Результаты проверки навыков</h3>
      {source && <p style={{ ...muted, margin: "0 0 1.5rem", wordBreak: "break-all" }}>{source}</p>}

      <div
        style={{
          padding: "1.2rem 1.5rem",
          marginBottom: "1.5rem",
          borderRadius: "var(--radius-m)",
          background: "var(--background-generic)",
          borderLeft: `0.3rem solid ${
            results.verdict === "block" ? "var(--status-negative)" : results.verdict === "review" ? "var(--status-warning)" : "var(--status-positive)"
          }`,
        }}
      >
        <div style={muted}>Итоговый вердикт платформы</div>
        <div style={{ margin: "0.5rem 0" }}>
          <span className={`badge ${verdict.badge}`} style={{ fontSize: "var(--font-body-size)", padding: "0.4rem 1.4rem" }}>
            {verdict.label}
          </span>
        </div>
        <div style={{ fontSize: "var(--font-caption-m-size)", color: "var(--text-700)" }}>
          {results.rejected
            ? "Архив отклонён при распаковке: у него признаки атаки на распаковщик, навыки не анализировались."
            : verdict.hint}
        </div>
        {!results.complete && (
          <div style={{ marginTop: "0.6rem", color: "var(--status-warning)", fontWeight: 500 }}>
            Проверка неполная: не все движки отработали — вердикт мог быть строже.
          </div>
        )}
        {!results.llm?.enabled && !results.rejected && (
          <div style={{ ...muted, marginTop: "0.6rem" }}>Семантический (LLM) анализ не выполнялся.</div>
        )}
      </div>

      {results.rejected && (
        <div style={{ marginBottom: "1.5rem" }}>
          <h4 style={{ marginBottom: "0.6rem" }}>Архив отклонён при распаковке</h4>
          <p style={{ margin: "0 0 0.6rem" }}>
            {REJECT_REASONS[results.rejected.reason] ?? results.rejected.reason}. Архив с такими признаками
            считается опасным сам по себе, загрузите навыки заново без них.
          </p>
          <div style={blockStyle}>{results.rejected.detail}</div>
        </div>
      )}

      {(results.warnings ?? []).map((warning, index) => (
        <div
          key={index}
          style={{
            padding: "0.6rem 1rem",
            marginBottom: "1rem",
            borderLeft: "0.3rem solid var(--status-warning)",
            background: "var(--background-generic)",
            fontSize: "var(--font-caption-m-size)",
          }}
        >
          {warning}
        </div>
      ))}

      {!results.rejected && (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
              gap: "1rem",
              marginBottom: "1.5rem",
            }}
          >
            <div style={tile}>
              <div style={muted}>Навыков</div>
              <div style={{ fontSize: "var(--font-header-s-size)", fontWeight: "bold", marginTop: "0.3rem" }}>{skills.length}</div>
            </div>
            {counts &&
              VERDICT_ORDER.map((name) => (
                <div key={name} style={tile}>
                  <span className={`badge ${VERDICTS[name].badge}`}>{name}</span>
                  <div style={{ fontSize: "var(--font-header-s-size)", fontWeight: "bold", marginTop: "0.3rem" }}>{counts[name] ?? 0}</div>
                </div>
              ))}
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
              gap: "1rem",
              marginBottom: "1.5rem",
            }}
          >
            <div style={tile}>
              <div style={muted}>Всего находок</div>
              <div style={{ fontSize: "var(--font-header-s-size)", fontWeight: "bold", marginTop: "0.3rem" }}>{results.summary?.total ?? 0}</div>
            </div>
            {SEVERITIES.map((severity) => (
              <div key={severity} style={tile}>
                <SeverityBadge severity={severity} />
                <div style={{ fontSize: "var(--font-header-s-size)", fontWeight: "bold", marginTop: "0.3rem" }}>{results.summary?.[severity] ?? 0}</div>
              </div>
            ))}
          </div>

          {engines.length > 0 && (
            <div style={{ marginBottom: "1.5rem" }}>
              <h4 style={{ marginBottom: "0.6rem" }}>Движки</h4>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                    <th style={{ padding: "1rem 1.2rem", textAlign: "left" }}>Движок</th>
                    <th style={{ padding: "1rem 1.2rem", textAlign: "left" }}>Версия</th>
                    <th style={{ padding: "1rem 1.2rem", textAlign: "left" }}>Статус</th>
                    <th style={{ padding: "1rem 1.2rem", textAlign: "left" }}>Время</th>
                  </tr>
                </thead>
                <tbody>
                  {engines.map(([name, engine]) => {
                    const status = ENGINE_STATUSES[engine.status] ?? { label: engine.status, badge: "badge-neutral" };
                    return (
                      <tr key={name} style={{ borderBottom: "0.1rem solid var(--separator-default)", verticalAlign: "top" }}>
                        <td style={{ padding: "1rem 1.2rem" }}>{engine.label}</td>
                        <td style={{ padding: "1rem 1.2rem", ...mono }}>{engine.version}</td>
                        <td style={{ padding: "1rem 1.2rem" }}>
                          <span className={`badge ${status.badge}`}>{status.label}</span>
                          {engine.skills_failed > 0 && (
                            <div style={{ ...muted, marginTop: "0.3rem" }}>
                              не отработал на {engine.skills_failed} из {skills.length}
                              {engine.error ? `: ${engine.error}` : ""}
                            </div>
                          )}
                        </td>
                        <td style={{ padding: "1rem 1.2rem", whiteSpace: "nowrap" }}>{formatDuration(engine.duration_sec)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "1rem", marginBottom: "1rem" }}>
            <h4 style={{ margin: 0 }}>Навыки</h4>
            <label style={{ ...muted, display: "flex", alignItems: "center", gap: "0.5rem", marginLeft: "auto" }}>
              Находки:
              <select className="input" value={minSeverity} onChange={(e) => setMinSeverity(e.target.value as SkillsSeverity)}>
                {FILTERS.map((filter) => (
                  <option key={filter.value} value={filter.value}>
                    {filter.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {results.findings_truncated && (
            <p style={{ ...muted, margin: "0 0 1rem" }}>
              Находок слишком много: в отчёт попали самые серьёзные, сводки и вердикт посчитаны по всем.
            </p>
          )}
          <p style={{ ...muted, margin: "0 0 1rem" }}>
            Нажмите на навык, чтобы раскрыть находки, и на находку — чтобы увидеть описание и рекомендацию. Тексты
            Cisco и SkillSpector — на языке движков.
          </p>
          {skills.map((skill) => (
            <SkillCard
              key={skill.path}
              skill={skill}
              minSeverity={minSeverity}
              defaultOpen={skills.length === 1 || skill.verdict === "block" || !skill.complete}
              engineLabel={engineLabel}
            />
          ))}
        </>
      )}
    </div>
  );
}
