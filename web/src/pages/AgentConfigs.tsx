import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { AgentConfig, InteractionMode } from "../api/types";
import { PageHeader } from "../components/PageHeader";

type EnvRow = { key: string; value: string };

const emptyEnv: EnvRow[] = [{ key: "", value: "" }];
const DEFAULT_REQUEST_BODY_TEMPLATE = '{\n  "message": "{{message}}"\n}';

export function AgentConfigs() {
  const [configs, setConfigs] = useState<AgentConfig[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);

  const [name, setName] = useState("");
  const [gitRepoUrl, setGitRepoUrl] = useState("");
  const [gitRef, setGitRef] = useState("main");
  const [gitAccessToken, setGitAccessToken] = useState("");
  const [dockerfilePath, setDockerfilePath] = useState("Dockerfile");
  const [envExamplePath, setEnvExamplePath] = useState("");
  const [apiPort, setApiPort] = useState("");
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
    setLanggraphBaseUrl("");
    setLanggraphAssistantId("agent");
    setLanggraphApiKey("");
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
    setAgentPurpose(c.agent_purpose ?? "");
    const rows = Object.entries(c.env_vars).map(([key, value]) => ({ key, value }));
    setEnvRows(rows.length ? rows : emptyEnv);
    setInteractionMode(c.interaction_mode);
    const apiConfig = c.api_config as Record<string, unknown> | null;
    setApiUrl((apiConfig?.url as string) ?? "");
    setApiMethod((apiConfig?.method as string) ?? "POST");
    setRequestBodyTemplate(apiConfig?.request_body_template ? JSON.stringify(apiConfig.request_body_template, null, 2) : DEFAULT_REQUEST_BODY_TEMPLATE);
    setResponseField((apiConfig?.response_field as string) ?? "reply");
    const langgraphConfig = c.langgraph_config as Record<string, unknown> | null;
    setLanggraphBaseUrl((langgraphConfig?.base_url as string) ?? "");
    setLanggraphAssistantId((langgraphConfig?.assistant_id as string) ?? "agent");
    setLanggraphApiKey((langgraphConfig?.api_key as string) ?? "");
    setShowForm(true);
  }

  function handleCancel() {
    resetForm();
    setEditingId(null);
    setShowForm(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const env_vars = Object.fromEntries(envRows.filter((r) => r.key).map((r) => [r.key, r.value]));
    const resources = cpu || memory ? { ...(cpu && { cpu }), ...(memory && { memory }) } : null;

    let api_config = null;
    if (interactionMode === "api") {
      try {
        api_config = {
          url: apiUrl,
          method: apiMethod,
          request_body_template: JSON.parse(requestBodyTemplate),
          response_field: responseField,
        };
      } catch {
        setError("Шаблон тела запроса должен быть валидным JSON");
        return;
      }
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
      agent_purpose: agentPurpose || null,
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
        await api.post("/agent-configs", payload);
      }
      handleCancel();
      load();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleDelete(id: number) {
    await api.delete(`/agent-configs/${id}`);
    load();
  }

  return (
    <div>
      <PageHeader
        title="Конфигурации агентов"
        description="Исходный код агента (git-репозиторий), его назначение и параметры запуска и взаимодействия. LLM-провайдер агента задаётся переменными окружения — платформа перехватывает трафик прозрачно."
        actions={
          <button className="btn" onClick={() => (showForm ? handleCancel() : setShowForm(true))}>
            {showForm ? "Отмена" : "Новая конфигурация"}
          </button>
        }
      />

      {error && (
        <div className="card" style={{ borderColor: "var(--color-danger)", marginBottom: "var(--space-4)" }}>
          {error}
        </div>
      )}

      {showForm && (
        <form className="card" onSubmit={handleSubmit} style={{ marginBottom: "var(--space-5)" }}>
          <div className="field">
            <label>Название</label>
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

          <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: "var(--space-4)" }}>
            <div className="field">
              <label>URL репозитория</label>
              <input
                value={gitRepoUrl}
                onChange={(e) => setGitRepoUrl(e.target.value)}
                placeholder="https://github.com/org/agent-repo.git"
                required
              />
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
            <label>Токен доступа (опционально — для приватных репозиториев по HTTPS)</label>
            <input
              type="password"
              value={gitAccessToken}
              onChange={(e) => setGitAccessToken(e.target.value)}
              placeholder="ghp_... / glpat-..."
            />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "var(--space-4)" }}>
            <div className="field">
              <label>Путь к .env.example (опционально)</label>
              <input value={envExamplePath} onChange={(e) => setEnvExamplePath(e.target.value)} placeholder=".env.example" />
            </div>
            <div className="field">
              <label>Порт API (опционально)</label>
              <input value={apiPort} onChange={(e) => setApiPort(e.target.value)} placeholder="8123" />
            </div>
          </div>

          <div className="field">
            <label>Команда запуска (опционально, через пробел)</label>
            <input value={entrypoint} onChange={(e) => setEntrypoint(e.target.value)} placeholder="python agent.py --flag" />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)" }}>
            <div className="field">
              <label>CPU (опционально)</label>
              <input value={cpu} onChange={(e) => setCpu(e.target.value)} placeholder="500m" />
            </div>
            <div className="field">
              <label>Память (опционально)</label>
              <input value={memory} onChange={(e) => setMemory(e.target.value)} placeholder="512Mi" />
            </div>
          </div>

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
            <label>Режим взаимодействия</label>
            <select value={interactionMode} onChange={(e) => setInteractionMode(e.target.value as InteractionMode)}>
              <option value="none">Нет (однократный запрос)</option>
              <option value="api">REST API</option>
              <option value="langgraph">LangGraph</option>
            </select>
          </div>

          {interactionMode === "api" && (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "var(--space-4)" }}>
                <div className="field">
                  <label>URL эндпоинта</label>
                  <input value={apiUrl} onChange={(e) => setApiUrl(e.target.value)} placeholder="/chat" />
                </div>
                <div className="field">
                  <label>Метод</label>
                  <select value={apiMethod} onChange={(e) => setApiMethod(e.target.value)}>
                    <option value="POST">POST</option>
                    <option value="GET">GET</option>
                  </select>
                </div>
              </div>
              <div className="field">
                <label>Шаблон тела запроса (JSON; {"{{message}}"} — место для сообщения)</label>
                <textarea rows={3} style={{ fontFamily: "monospace" }} value={requestBodyTemplate} onChange={(e) => setRequestBodyTemplate(e.target.value)} />
              </div>
              <div className="field">
                <label>Поле ответа (dot-path в JSON, например "reply" или "data.0.text")</label>
                <input value={responseField} onChange={(e) => setResponseField(e.target.value)} placeholder="reply" />
              </div>
            </>
          )}

          {interactionMode === "langgraph" && (
            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: "var(--space-4)" }}>
              <div className="field">
                <label>Базовый URL LangGraph</label>
                <input value={langgraphBaseUrl} onChange={(e) => setLanggraphBaseUrl(e.target.value)} placeholder="http://agent-pod:8123" />
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
          )}

          <button className="btn" type="submit">{editingId ? "Сохранить" : "Создать"}</button>
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
                <td><span className="badge badge-neutral">{c.interaction_mode}</span></td>
                <td style={{ display: "flex", gap: 8 }}>
                  <button className="btn btn-secondary" onClick={() => handleEdit(c)}>Изменить</button>
                  <button className="btn btn-secondary" onClick={() => handleDelete(c.id)}>Удалить</button>
                </td>
              </tr>
            ))}
            {configs.length === 0 && (
              <tr><td colSpan={6} style={{ color: "var(--color-text-muted)" }}>Нет конфигураций.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
