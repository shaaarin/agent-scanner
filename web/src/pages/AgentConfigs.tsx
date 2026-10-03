import { useEffect, useState } from "react";
import { api, launcherApi } from "../api/client";
import type { AgentConfig, InteractionMode } from "../api/types";
import { PageHeader } from "../components/PageHeader";

type EnvRow = { key: string; value: string };

interface RepoBranchesResponse {
  branches: string[];
}

interface RepoInspectResponse {
  dockerfiles: string[];
  env_examples: Record<string, Record<string, string>>;
}

const emptyEnv: EnvRow[] = [{ key: "", value: "" }];
const DEFAULT_REQUEST_BODY_TEMPLATE = '{\n  "message": "{{message}}"\n}';
const DEFAULT_TEXT_BODY_TEMPLATE = "{{message}}";
const PREVIEW_MESSAGE = 'Привет! Покажи "статус" заказа';
const PREVIEW_SESSION_ID = "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed";

type BodyFormat = "json" | "form" | "text";

// Та же подстановка, что в scanner/deepteam/app/target.py::render_request --
// только для предпросмотра в форме.
function fillPlaceholders(text: string, urlEncode = false): string {
  const enc = (v: string) => (urlEncode ? encodeURIComponent(v) : v);
  return text.split("{{message}}").join(enc(PREVIEW_MESSAGE)).split("{{session_id}}").join(enc(PREVIEW_SESSION_ID));
}

function substituteJson(node: unknown): unknown {
  if (typeof node === "string") return fillPlaceholders(node);
  if (Array.isArray(node)) return node.map(substituteJson);
  if (node && typeof node === "object") {
    return Object.fromEntries(Object.entries(node as Record<string, unknown>).map(([k, v]) => [k, substituteJson(v)]));
  }
  return node;
}

function renderRequestPreview(
  url: string,
  method: string,
  bodyFormat: BodyFormat,
  template: string,
  headers: EnvRow[],
): string {
  const lines = [`${method} ${fillPlaceholders(url || "/", true)}`];
  const hdrs = headers.filter((h) => h.key).map((h) => `${h.key}: ${fillPlaceholders(h.value)}`);
  try {
    if (bodyFormat === "text") {
      if (!hdrs.some((h) => h.toLowerCase().startsWith("content-type:"))) hdrs.push("Content-Type: text/plain; charset=utf-8");
      return [...lines, ...hdrs, "", fillPlaceholders(template)].join("\n");
    }
    const parsed = template.trim() ? JSON.parse(template) : null;
    const body = substituteJson(parsed);
    if (method === "GET") {
      const query = body && typeof body === "object" ? new URLSearchParams(body as Record<string, string>).toString() : "";
      return [query ? `${lines[0]}${lines[0].includes("?") ? "&" : "?"}${query}` : lines[0], ...hdrs].join("\n");
    }
    if (bodyFormat === "form") {
      const form = new URLSearchParams(Object.entries((body ?? {}) as Record<string, unknown>).map(([k, v]) => [k, String(v)])).toString();
      return [...lines, ...hdrs, "Content-Type: application/x-www-form-urlencoded", "", form].join("\n");
    }
    return [...lines, ...hdrs, "Content-Type: application/json", "", JSON.stringify(body, null, 2)].join("\n");
  } catch {
    return "Шаблон тела — некорректный JSON";
  }
}

const interactionModeLabel: Record<string, string> = {
  none: "Без диалога",
  api: "REST API",
  langgraph: "LangGraph",
};

function repoNameFromUrl(url: string): string {
  const match = url.match(/([^/]+?)(\.git)?\/?$/);
  return (match?.[1] || "agent").toLowerCase().replace(/[^a-z0-9-]+/g, "-");
}

export function AgentConfigs() {
  const [configs, setConfigs] = useState<AgentConfig[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);

  // Creation wizard: step 1 (load repo) -> step 2 (configure, informed by
  // what step 1 discovered). Irrelevant when editing (editingId set) --
  // editing shows a flat form instead, see below.
  //
  // draftId: a real AgentConfig row created as soon as step 1 succeeds
  // (not just held in local component state) -- otherwise closing the tab,
  // navigating away, or anything interrupting the wizard before the final
  // "Создать" loses everything the (potentially slow) repo load/inspect
  // already did. Step 2 just keeps updating this same row via PUT
  // (exclude_unset semantics server-side, so partial updates are fine)
  // instead of POSTing a brand new one at the end.
  const [draftId, setDraftId] = useState<number | null>(null);
  const [wizardStep, setWizardStep] = useState<"repo" | "configure">("repo");
  const [loadingRepo, setLoadingRepo] = useState(false);
  const [inspecting, setInspecting] = useState(false);
  const [branches, setBranches] = useState<string[]>([]);
  const [dockerfiles, setDockerfiles] = useState<string[]>([]);
  const [envExamples, setEnvExamples] = useState<Record<string, Record<string, string>>>({});
  const [selectedEnvExample, setSelectedEnvExample] = useState("");

  const [name, setName] = useState("");
  const [gitRepoUrl, setGitRepoUrl] = useState("");
  const [gitRef, setGitRef] = useState("main");
  const [gitAccessToken, setGitAccessToken] = useState("");
  const [dockerfilePath, setDockerfilePath] = useState("Dockerfile");
  const [envExamplePath, setEnvExamplePath] = useState("");
  const [apiPort, setApiPort] = useState("");
  // entrypoint/cpu/memory: no longer exposed as form fields (the user's
  // view is that these belong in the Dockerfile/image, not a platform-level
  // override) -- kept as state only so editing an existing config that
  // already has them set (e.g. via the API) doesn't silently clobber them
  // in the PUT payload below.
  const [entrypoint, setEntrypoint] = useState("");
  const [cpu, setCpu] = useState("");
  const [memory, setMemory] = useState("");
  const [agentPurpose, setAgentPurpose] = useState("");
  const [envRows, setEnvRows] = useState<EnvRow[]>(emptyEnv);
  const [interactionMode, setInteractionMode] = useState<InteractionMode>("none");

  const [apiUrl, setApiUrl] = useState("");
  const [apiMethod, setApiMethod] = useState("POST");
  const [requestBodyTemplate, setRequestBodyTemplate] = useState(DEFAULT_REQUEST_BODY_TEMPLATE);
  const [responseField, setResponseField] = useState("reply");
  const [bodyFormat, setBodyFormat] = useState<BodyFormat>("json");
  const [apiHeaders, setApiHeaders] = useState<EnvRow[]>(emptyEnv);
  const [healthPath, setHealthPath] = useState("");

  const [langgraphBaseUrl, setLanggraphBaseUrl] = useState("");
  const [langgraphAssistantId, setLanggraphAssistantId] = useState("agent");
  const [langgraphApiKey, setLanggraphApiKey] = useState("");

  const load = () =>
    api.get<AgentConfig[]>("/agent-configs").then(setConfigs).catch((e) => setError(String(e)));

  useEffect(() => {
    load();
  }, []);

  function updateEnvRow(i: number, field: "key" | "value", value: string) {
    setEnvRows((rows) => rows.map((r, idx) => (idx === i ? { ...r, [field]: value } : r)));
  }

  function resetForm() {
    setName("");
    setGitRepoUrl("");
    setGitRef("main");
    setGitAccessToken("");
    setDockerfilePath("Dockerfile");
    setEnvExamplePath("");
    setApiPort("");
    setEntrypoint("");
    setCpu("");
    setMemory("");
    setAgentPurpose("");
    setEnvRows(emptyEnv);
    setInteractionMode("none");
    setApiUrl("");
    setApiMethod("POST");
    setRequestBodyTemplate(DEFAULT_REQUEST_BODY_TEMPLATE);
    setResponseField("reply");
    setBodyFormat("json");
    setApiHeaders(emptyEnv);
    setHealthPath("");
    setLanggraphBaseUrl("");
    setLanggraphAssistantId("agent");
    setLanggraphApiKey("");
    setWizardStep("repo");
    setBranches([]);
    setDockerfiles([]);
    setEnvExamples({});
    setSelectedEnvExample("");
    setDraftId(null);
  }

  function handleEdit(c: AgentConfig) {
    setEditingId(c.id);
    setName(c.name);
    setGitRepoUrl(c.git_repo_url);
    setGitRef(c.git_ref);
    setGitAccessToken(c.git_access_token ?? "");
    setDockerfilePath(c.dockerfile_path);
    setEnvExamplePath(c.env_example_path ?? "");
    setApiPort(c.api_port ? String(c.api_port) : "");
    setEntrypoint(c.entrypoint ? c.entrypoint.join(" ") : "");
    setCpu((c.resources?.cpu as string) ?? "");
    setMemory((c.resources?.memory as string) ?? "");
    const rows = Object.entries(c.env_vars).map(([key, value]) => ({ key, value }));
    setEnvRows(rows.length ? rows : emptyEnv);
    setInteractionMode(c.interaction_mode);
    const apiConfig = c.api_config as Record<string, unknown> | null;
    setApiUrl((apiConfig?.url as string) ?? "");
    setApiMethod((apiConfig?.method as string) ?? "POST");
    const storedTemplate = apiConfig?.request_body_template;
    setRequestBodyTemplate(
      storedTemplate === undefined || storedTemplate === null
        ? DEFAULT_REQUEST_BODY_TEMPLATE
        : typeof storedTemplate === "string"
        ? storedTemplate
        : JSON.stringify(storedTemplate, null, 2),
    );
    setResponseField((apiConfig?.response_field as string) ?? "reply");
    setBodyFormat(((apiConfig?.body_format as BodyFormat) ?? "json"));
    const storedHeaders = Object.entries((apiConfig?.headers as Record<string, string>) ?? {}).map(([key, value]) => ({ key, value }));
    setApiHeaders(storedHeaders.length ? storedHeaders : emptyEnv);
    setHealthPath((apiConfig?.health_path as string) ?? "");
    const langgraphConfig = c.langgraph_config as Record<string, unknown> | null;
    setLanggraphBaseUrl((langgraphConfig?.base_url as string) ?? "");
    setLanggraphAssistantId((langgraphConfig?.assistant_id as string) ?? "agent");
    setLanggraphApiKey((langgraphConfig?.api_key as string) ?? "");
    setShowForm(true);
  }

  function closeForm() {
    resetForm();
    setEditingId(null);
    setShowForm(false);
  }

  async function handleCancel() {
    // An explicit cancel (as opposed to just navigating away, which the
    // draft is specifically meant to survive) abandons the in-progress
    // draft for real -- otherwise every cancelled wizard leaves a
    // half-configured AgentConfig behind forever. Not run on a *successful*
    // submit (see handleSubmit, which calls closeForm() directly instead) --
    // by then the draft has just become the real, finished config.
    if (draftId && !editingId) {
      await api.delete(`/agent-configs/${draftId}`).catch(() => {});
      load();
    }
    closeForm();
  }

  function applyEnvExample(path: string, examples: Record<string, Record<string, string>>) {
    setSelectedEnvExample(path);
    setEnvExamplePath(path);
    const parsed = examples[path] ?? {};
    const rows = Object.entries(parsed).map(([key, value]) => ({ key, value }));
    setEnvRows(rows.length ? rows : emptyEnv);
  }

  function handleEnvExampleChange(path: string) {
    if (!path) {
      setSelectedEnvExample("");
      setEnvExamplePath("");
      setEnvRows(emptyEnv);
      return;
    }
    applyEnvExample(path, envExamples);
  }

  async function loadInspect(ref: string) {
    setInspecting(true);
    setError(null);
    try {
      const result = await launcherApi.post<RepoInspectResponse>("/repo/inspect", {
        git_repo_url: gitRepoUrl,
        git_ref: ref,
        git_access_token: gitAccessToken || null,
      });
      setDockerfiles(result.dockerfiles);
      setEnvExamples(result.env_examples);
      setDockerfilePath(result.dockerfiles[0] ?? "Dockerfile");
      const envPaths = Object.keys(result.env_examples);
      if (envPaths.length > 0) {
        applyEnvExample(envPaths[0], result.env_examples);
      } else {
        setSelectedEnvExample("");
        setEnvExamplePath("");
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setInspecting(false);
    }
  }

  async function handleLoadRepo() {
    setError(null);
    setLoadingRepo(true);
    try {
      const result = await launcherApi.post<RepoBranchesResponse>("/repo/branches", {
        git_repo_url: gitRepoUrl,
        git_access_token: gitAccessToken || null,
      });
      setBranches(result.branches);
      const defaultBranch = result.branches[0];
      setGitRef(defaultBranch);

      const draftFields = {
        name: name.trim() || `${repoNameFromUrl(gitRepoUrl)}-${Math.random().toString(36).slice(2, 6)}`,
        git_repo_url: gitRepoUrl,
        git_ref: defaultBranch,
        git_access_token: gitAccessToken || null,
        agent_purpose: agentPurpose || null,
      };
      if (draftId) {
        await api.put(`/agent-configs/${draftId}`, draftFields);
      } else {
        const draft = await api.post<AgentConfig>("/agent-configs", draftFields);
        setDraftId(draft.id);
        setName(draft.name);
      }

      setWizardStep("configure");
      await loadInspect(defaultBranch);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingRepo(false);
    }
  }

  async function handleBranchChange(ref: string) {
    setGitRef(ref);
    if (draftId) {
      await api.put(`/agent-configs/${draftId}`, { git_ref: ref });
    }
    await loadInspect(ref);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const env_vars = Object.fromEntries(envRows.filter((r) => r.key).map((r) => [r.key, r.value]));
    const resources = cpu || memory ? { ...(cpu && { cpu }), ...(memory && { memory }) } : null;

    let api_config = null;
    if (interactionMode === "api") {
      let request_body_template: unknown = requestBodyTemplate;
      if (bodyFormat !== "text") {
        try {
          request_body_template = requestBodyTemplate.trim() ? JSON.parse(requestBodyTemplate) : null;
        } catch {
          setError("Проверьте шаблон тела запроса: для форматов JSON и form нужен корректный JSON.");
          return;
        }
        if (bodyFormat === "form" && (request_body_template === null || typeof request_body_template !== "object" || Array.isArray(request_body_template))) {
          setError("Для формата form шаблон тела должен быть JSON-объектом {\"поле\": \"значение\"}.");
          return;
        }
      }
      const headers = Object.fromEntries(apiHeaders.filter((h) => h.key.trim()).map((h) => [h.key.trim(), h.value]));
      api_config = {
        url: apiUrl,
        method: apiMethod,
        body_format: bodyFormat,
        request_body_template,
        headers,
        response_field: responseField,
        ...(healthPath.trim() && { health_path: healthPath.trim() }),
      };
    }

    const payload = {
      name,
      git_repo_url: gitRepoUrl,
      git_ref: gitRef,
      git_access_token: gitAccessToken || null,
      dockerfile_path: dockerfilePath,
      env_example_path: envExamplePath || null,
      api_port: apiPort ? Number(apiPort) : null,
      entrypoint: entrypoint ? entrypoint.split(" ").filter(Boolean) : null,
      env_vars,
      resources,
      interaction_mode: interactionMode,
      api_config,
      langgraph_config:
        interactionMode === "langgraph"
          ? { base_url: langgraphBaseUrl, assistant_id: langgraphAssistantId, api_key: langgraphApiKey || null }
          : null,
    };

    try {
      if (editingId) {
        await api.put(`/agent-configs/${editingId}`, payload);
      } else {
        // draftId always exists by the time step 2 can submit -- created
        // in handleLoadRepo as soon as step 1 succeeds. PUT finishes the
        // same row rather than POSTing a separate final one.
        await api.put(`/agent-configs/${draftId}`, payload);
      }
      closeForm();
      load();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleDelete(id: number) {
    await api.delete(`/agent-configs/${id}`);
    load();
  }

  // Shared between the wizard's step 2 and the flat edit form.
  function renderConfigureFields() {
    return (
      <>
        <div className="field">
          <label>Переменные окружения</label>
          {envRows.map((row, i) => (
            <div key={i} style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              <input placeholder="KEY" value={row.key} onChange={(e) => updateEnvRow(i, "key", e.target.value)} />
              <input placeholder="значение" value={row.value} onChange={(e) => updateEnvRow(i, "value", e.target.value)} />
            </div>
          ))}
          <button type="button" className="btn btn-secondary" onClick={() => setEnvRows((r) => [...r, { key: "", value: "" }])}>
            + Добавить переменную
          </button>
        </div>

        <div className="field">
          <label>Порт API · необязательно</label>
          <input value={apiPort} onChange={(e) => setApiPort(e.target.value)} placeholder="8123" />
          <p style={{ fontSize: 12, color: "var(--text-500)", margin: "0.4rem 0 0" }}>
            Если указать порт, платформа сама пробросит адрес агента после запуска.
          </p>
        </div>

        <div className="field">
          <label>Режим взаимодействия</label>
          <select value={interactionMode} onChange={(e) => setInteractionMode(e.target.value as InteractionMode)}>
            <option value="none">Без диалога (только LLM-трафик)</option>
            <option value="api">REST API</option>
            <option value="langgraph">LangGraph</option>
          </select>
        </div>

        {interactionMode === "api" && (
          <>
            <p style={{ fontSize: 12, color: "var(--text-500)", margin: "0 0 1.2rem" }}>
              Любой HTTP API агента. Плейсхолдеры: <code>{"{{message}}"}</code> — сообщение атаки,{" "}
              <code>{"{{session_id}}"}</code> — новый id на каждый разговор. Их можно ставить в путь и
              параметры URL, заголовки и тело. Если задан «Порт API», хост и порт в URL платформа
              подставит сама — достаточно пути, например <code>/chat</code>.
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: "1.6rem" }}>
              <div className="field">
                <label>URL эндпоинта агента</label>
                <input value={apiUrl} onChange={(e) => setApiUrl(e.target.value)} placeholder="/chat" />
              </div>
              <div className="field">
                <label>Метод</label>
                <select value={apiMethod} onChange={(e) => setApiMethod(e.target.value)}>
                  <option value="POST">POST</option>
                  <option value="GET">GET</option>
                  <option value="PUT">PUT</option>
                  <option value="PATCH">PATCH</option>
                </select>
              </div>
              <div className="field">
                <label>Формат тела</label>
                <select
                  value={bodyFormat}
                  onChange={(e) => {
                    const next = e.target.value as BodyFormat;
                    if (next === "text" && requestBodyTemplate === DEFAULT_REQUEST_BODY_TEMPLATE) setRequestBodyTemplate(DEFAULT_TEXT_BODY_TEMPLATE);
                    if (next !== "text" && requestBodyTemplate === DEFAULT_TEXT_BODY_TEMPLATE) setRequestBodyTemplate(DEFAULT_REQUEST_BODY_TEMPLATE);
                    setBodyFormat(next);
                  }}
                >
                  <option value="json">JSON</option>
                  <option value="form">Форма (x-www-form-urlencoded)</option>
                  <option value="text">Текст</option>
                </select>
              </div>
            </div>
            <div className="field">
              <label>
                Шаблон тела запроса
                {bodyFormat === "text" ? " · произвольный текст" : " · JSON, плейсхолдеры внутри строк"}
                {apiMethod === "GET" && bodyFormat !== "text" ? " · для GET поля уйдут в параметры URL" : ""}
              </label>
              <textarea rows={5} style={{ fontFamily: "monospace" }} value={requestBodyTemplate} onChange={(e) => setRequestBodyTemplate(e.target.value)} />
            </div>
            <div className="field">
              <label>Заголовки · необязательно</label>
              {apiHeaders.map((row, i) => (
                <div key={i} style={{ display: "flex", gap: 8, marginBottom: 8 }}>
                  <input
                    placeholder="Authorization"
                    value={row.key}
                    onChange={(e) => setApiHeaders((rows) => rows.map((r, idx) => (idx === i ? { ...r, key: e.target.value } : r)))}
                  />
                  <input
                    placeholder="Bearer ..."
                    value={row.value}
                    onChange={(e) => setApiHeaders((rows) => rows.map((r, idx) => (idx === i ? { ...r, value: e.target.value } : r)))}
                  />
                </div>
              ))}
              <button type="button" className="btn btn-secondary" onClick={() => setApiHeaders((r) => [...r, { key: "", value: "" }])}>
                + Добавить заголовок
              </button>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "1.6rem" }}>
              <div className="field">
                <label>Поле ответа · путь в JSON</label>
                <input value={responseField} onChange={(e) => setResponseField(e.target.value)} placeholder="reply" />
                <p style={{ fontSize: 12, color: "var(--text-500)", margin: "0.4rem 0 0" }}>
                  Например <code>reply</code>, <code>data.0.text</code>, <code>messages.-1.content</code> (−1 — последний
                  элемент). Пусто — весь ответ как текст. Если поля нет, кейс считается ошибкой.
                </p>
              </div>
              <div className="field">
                <label>Путь проверки готовности</label>
                <input value={healthPath} onChange={(e) => setHealthPath(e.target.value)} placeholder="как раньше: …/ok" />
                <p style={{ fontSize: 12, color: "var(--text-500)", margin: "0.4rem 0 0" }}>
                  Агент готов, когда этот путь отвечает кодом ниже 500. Пусто — путь эндпоинта без <code>/chat</code> +{" "}
                  <code>/ok</code>, а если в пути есть плейсхолдер — <code>/</code>.
                </p>
              </div>
            </div>
            <div className="field">
              <label>Пример запроса · с сообщением «{PREVIEW_MESSAGE}»</label>
              <pre
                style={{
                  margin: 0,
                  padding: "1rem",
                  background: "var(--background-generic)",
                  borderRadius: "var(--radius-m)",
                  fontSize: 12,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-all",
                }}
              >
                {renderRequestPreview(apiUrl, apiMethod, bodyFormat, requestBodyTemplate, apiHeaders)}
              </pre>
            </div>
          </>
        )}

        {interactionMode === "langgraph" && (
          <>
            <p style={{ fontSize: 12, color: "var(--text-500)", margin: "0 0 1.2rem" }}>
              Базовый URL обычно указывать не нужно: если заполнен «Порт API», платформа
              определит адрес сама после запуска агента. Укажите его вручную только если
              порт не задан (например, адрес проброшен через <code>kubectl expose</code>).
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: "1.6rem" }}>
              <div className="field">
                <label>Базовый URL LangGraph (опционально — заполняется автоматически)</label>
                <input value={langgraphBaseUrl} onChange={(e) => setLanggraphBaseUrl(e.target.value)} placeholder="определится автоматически после запуска" />
              </div>
              <div className="field">
                <label>ID ассистента / графа</label>
                <input value={langgraphAssistantId} onChange={(e) => setLanggraphAssistantId(e.target.value)} placeholder="agent" />
              </div>
              <div className="field">
                <label>API-ключ (опционально)</label>
                <input type="password" value={langgraphApiKey} onChange={(e) => setLanggraphApiKey(e.target.value)} />
              </div>
            </div>
          </>
        )}
      </>
    );
  }

  return (
    <div>
      <PageHeader
        title="Конфигурации агентов"
        description="Репозиторий, параметры запуска и способ общения с тестируемым агентом. Учётные данные его LLM-провайдера платформа перехватывает сама — отдельно указывать их не нужно."
        actions={
          <button className="btn" onClick={() => (showForm ? handleCancel() : setShowForm(true))}>
            {showForm ? "Отмена" : "Новая конфигурация"}
          </button>
        }
      />

      {error && (
        <div className="card" style={{ borderColor: "var(--status-negative)", marginBottom: "1.6rem" }}>
          {error}
        </div>
      )}

      {showForm && editingId && (
        <form className="card" onSubmit={handleSubmit} style={{ marginBottom: "2.4rem" }}>
          <div className="field">
            <label>Название конфигурации</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="field">
            <label>Назначение агента</label>
            <textarea
              rows={2}
              value={agentPurpose}
              onChange={(e) => setAgentPurpose(e.target.value)}
              placeholder="Ассистент службы поддержки интернет-магазина книг."
            />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: "1.6rem" }}>
            <div className="field">
              <label>Репозиторий (git URL)</label>
              <input value={gitRepoUrl} onChange={(e) => setGitRepoUrl(e.target.value)} required />
            </div>
            <div className="field">
              <label>Ветка / тег</label>
              <input value={gitRef} onChange={(e) => setGitRef(e.target.value)} placeholder="main" />
            </div>
            <div className="field">
              <label>Путь к Dockerfile</label>
              <input value={dockerfilePath} onChange={(e) => setDockerfilePath(e.target.value)} placeholder="Dockerfile" />
            </div>
          </div>
          <div className="field">
            <label>Токен доступа · только для приватных репозиториев по HTTPS</label>
            <input
              type="password"
              value={gitAccessToken}
              onChange={(e) => setGitAccessToken(e.target.value)}
              placeholder="ghp_... / glpat-..."
            />
          </div>
          <div className="field">
            <label>Файл .env.example · необязательно</label>
            <input value={envExamplePath} onChange={(e) => setEnvExamplePath(e.target.value)} placeholder=".env.example" />
          </div>

          {renderConfigureFields()}

          <button className="btn" type="submit" style={{ marginTop: "1.6rem" }}>Сохранить</button>
        </form>
      )}

      {showForm && !editingId && wizardStep === "repo" && (
        <div className="card" style={{ marginBottom: "2.4rem" }}>
          <h2 style={{ marginTop: 0 }}>Шаг 1. Репозиторий</h2>
          <p style={{ fontSize: 13, color: "var(--text-500)", margin: "0 0 1.6rem" }}>
            Укажите репозиторий агента — дальше платформа сама найдёт ветки, Dockerfile и пример переменных окружения.
          </p>
          <div className="field">
            <label>Название конфигурации</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="field">
            <label>Назначение агента</label>
            <textarea
              rows={2}
              value={agentPurpose}
              onChange={(e) => setAgentPurpose(e.target.value)}
              placeholder="Ассистент службы поддержки интернет-магазина книг."
            />
          </div>
          <div className="field">
            <label>Репозиторий (git URL)</label>
            <input
              value={gitRepoUrl}
              onChange={(e) => setGitRepoUrl(e.target.value)}
              placeholder="https://gitlab.com/org/agent-repo.git"
              required
            />
          </div>
          <div className="field">
            <label>Токен доступа · только для приватных репозиториев по HTTPS</label>
            <input
              type="password"
              value={gitAccessToken}
              onChange={(e) => setGitAccessToken(e.target.value)}
              placeholder="ghp_... / glpat-..."
            />
          </div>
          <button
            className="btn"
            type="button"
            onClick={handleLoadRepo}
            disabled={loadingRepo || !gitRepoUrl}
          >
            {loadingRepo ? "Загрузка…" : "Загрузить репозиторий"}
          </button>
          {!name && (
            <p style={{ fontSize: 12, color: "var(--text-500)", margin: "0.6rem 0 0" }}>
              Название можно задать позже, на шаге 2.
            </p>
          )}
        </div>
      )}

      {showForm && !editingId && wizardStep === "configure" && (
        <form className="card" onSubmit={handleSubmit} style={{ marginBottom: "2.4rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h2 style={{ marginTop: 0 }}>Шаг 2. Настройка</h2>
            <button type="button" className="btn btn-secondary" onClick={() => setWizardStep("repo")}>
              ← К репозиторию
            </button>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.6rem" }}>
            <div className="field">
              <label>Ветка</label>
              <select value={gitRef} onChange={(e) => handleBranchChange(e.target.value)} disabled={inspecting}>
                {branches.map((b) => (
                  <option key={b} value={b}>{b}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Dockerfile</label>
              {dockerfiles.length > 0 ? (
                <select value={dockerfilePath} onChange={(e) => setDockerfilePath(e.target.value)} disabled={inspecting}>
                  {dockerfiles.map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </select>
              ) : (
                <input value={dockerfilePath} onChange={(e) => setDockerfilePath(e.target.value)} placeholder="Dockerfile" />
              )}
              {!inspecting && dockerfiles.length === 0 && (
                <p style={{ fontSize: 12, color: "var(--text-600)", margin: "0.4rem 0 0" }}>
                  Dockerfile не найден — укажите путь вручную.
                </p>
              )}
            </div>
          </div>

          <div className="field">
            <label>.env.example</label>
            <select value={selectedEnvExample} onChange={(e) => handleEnvExampleChange(e.target.value)} disabled={inspecting}>
              <option value="">Нет</option>
              {Object.keys(envExamples).map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
            {inspecting && <p style={{ fontSize: 12, color: "var(--text-600)", margin: "0.4rem 0 0" }}>Анализ репозитория…</p>}
          </div>

          {renderConfigureFields()}

          <button className="btn" type="submit" style={{ marginTop: "1.6rem" }} disabled={inspecting}>Создать</button>
        </form>
      )}

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <table>
          <thead>
            <tr>
              <th>Название</th>
              <th>Репозиторий</th>
              <th>Ветка</th>
              <th>Переменные</th>
              <th>Взаимодействие</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {configs.map((c) => (
              <tr key={c.id}>
                <td><strong>{c.name}</strong></td>
                <td><code>{c.git_repo_url}</code></td>
                <td>{c.git_ref}</td>
                <td>{Object.keys(c.env_vars).length}</td>
                <td><span className="badge badge-neutral">{interactionModeLabel[c.interaction_mode] ?? c.interaction_mode}</span></td>
                <td>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button className="btn btn-secondary" onClick={() => handleEdit(c)}>Изменить</button>
                    <button className="btn btn-secondary" onClick={() => handleDelete(c.id)}>Удалить</button>
                  </div>
                </td>
              </tr>
            ))}
            {configs.length === 0 && (
              <tr>
                <td colSpan={6} style={{ color: "var(--text-500)", padding: "2.4rem", textAlign: "center" }}>
                  Пока нет конфигураций. Добавьте агента, чтобы начать.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
