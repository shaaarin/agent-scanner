import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type {
  AgentConfig,
  AttackPrompt,
  Campaign,
  CampaignStatus,
  FuzzMode,
  FuzzRun,
  LLMModelListItem,
  TreeRun,
} from "../api/types";
import { PageHeader } from "../components/PageHeader";

const emptyForm = {
  name: "",
  session_id: "",
  agent_config_id: "",
  interactor_llm_model_id: "",
  generator_llm_model_id: "",
  user_instruction: "",
  directEnabled: false,
  directMode: "non_adaptive" as FuzzMode,
  directMaxIterations: 20,
  directStopOnSuccess: true,
  directAttackPromptIds: [] as number[],
  indirectEnabled: false,
  indirectMode: "non_adaptive" as FuzzMode,
  indirectAttemptsPerCheckpoint: 5,
  indirectMaxCheckpoints: "",
  indirectAttackPromptIds: [] as number[],
  judgeLlmModelId: "",
};

const statusLabel: Record<string, string> = {
  new: "новое",
  active: "активно",
  paused: "на паузе",
  cancelled: "отменено",
};

const statusBadgeClass: Record<string, string> = {
  active: "badge-success",
  cancelled: "badge-danger",
};

const interactionModeLabel: Record<string, string> = {
  none: "без диалога",
  api: "REST API",
  langgraph: "LangGraph",
};

const fuzzModeLabel: Record<string, string> = {
  non_adaptive: "фиксированный набор атак",
  adaptive: "адаптивный (учитывает предыдущие попытки)",
};

function slugify(text: string): string {
  const slug = text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug || "scan";
}

function generateSessionId(name: string): string {
  const date = new Date().toISOString().slice(0, 10);
  const rand = Math.random().toString(36).slice(2, 6);
  return `${slugify(name)}-${date}-${rand}`;
}

export function Campaigns() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [fuzzRuns, setFuzzRuns] = useState<FuzzRun[]>([]);
  const [treeRuns, setTreeRuns] = useState<TreeRun[]>([]);
  const [llmModels, setLlmModels] = useState<LLMModelListItem[]>([]);
  const [agentConfigs, setAgentConfigs] = useState<AgentConfig[]>([]);
  const [attackPrompts, setAttackPrompts] = useState<AttackPrompt[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);

  const load = () => {
    api.get<Campaign[]>("/campaigns").then(setCampaigns).catch((e) => setError(String(e)));
    api.get<FuzzRun[]>("/fuzz-runs").then(setFuzzRuns);
    api.get<TreeRun[]>("/tree-runs").then(setTreeRuns);
    api.get<LLMModelListItem[]>("/llm-models").then(setLlmModels);
    api.get<AgentConfig[]>("/agent-configs").then(setAgentConfigs);
    api.get<AttackPrompt[]>("/attack-prompts").then(setAttackPrompts);
  };

  useEffect(() => {
    load();
  }, []);

  const agentConfigId = form.agent_config_id ? Number(form.agent_config_id) : null;
  const selectedAgentConfig = agentConfigs.find((a) => a.id === agentConfigId);
  const needsInteractor = selectedAgentConfig && selectedAgentConfig.interaction_mode !== "none";

  const fuzzRunByCampaign = new Map(fuzzRuns.map((f) => [f.base_campaign_id, f]));
  const treeRunByCampaign = new Map(treeRuns.map((t) => [t.base_campaign_id, t]));
  // AttackPrompt carries no delivery target -- the same checklist is offered
  // for both direct and indirect, each section keeps its own selection.

  function toggleAttackPrompt(field: "directAttackPromptIds" | "indirectAttackPromptIds", id: number) {
    setForm((f) => ({
      ...f,
      [field]: f[field].includes(id) ? f[field].filter((x) => x !== id) : [...f[field], id],
    }));
  }

  function handleEdit(c: Campaign) {
    setEditingId(c.id);
    setForm({
      ...emptyForm,
      name: c.name,
      session_id: c.session_id,
      agent_config_id: c.agent_config_id ? String(c.agent_config_id) : "",
      interactor_llm_model_id: c.interactor_llm_model_id ? String(c.interactor_llm_model_id) : "",
      generator_llm_model_id: c.generator_llm_model_id ? String(c.generator_llm_model_id) : "",
      user_instruction: c.user_instruction ?? "",
    });
    setShowForm(true);
  }

  function handleCancel() {
    setForm(emptyForm);
    setEditingId(null);
    setShowForm(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if ((form.directEnabled || form.indirectEnabled) && !form.judgeLlmModelId) {
      setError("Выберите модель судьи: она обязательна для прямого и индирект-фаззинга.");
      return;
    }
    try {
      if (editingId) {
        // session_id is immutable once a campaign exists (tied to the k8s
        // namespace/proxy session) -- CampaignUpdate doesn't accept it.
        await api.patch(`/campaigns/${editingId}`, {
          name: form.name,
          agent_config_id: form.agent_config_id ? Number(form.agent_config_id) : null,
          interactor_llm_model_id: form.interactor_llm_model_id ? Number(form.interactor_llm_model_id) : null,
          generator_llm_model_id: form.generator_llm_model_id ? Number(form.generator_llm_model_id) : null,
          interactor_persona: needsInteractor ? "benign_user" : null,
          user_instruction: form.user_instruction || null,
        });
        const hasFuzzRun = fuzzRunByCampaign.has(editingId);
        const hasTreeRun = treeRunByCampaign.has(editingId);
        if (form.directEnabled && !hasFuzzRun) {
          await api.post("/fuzz-runs", {
            name: `${form.name}-direct`,
            base_campaign_id: editingId,
            injection_target: "user_message",
            mode: form.directMode,
            max_iterations: Number(form.directMaxIterations),
            stop_on_success: form.directStopOnSuccess,
            judge_llm_model_id: form.judgeLlmModelId ? Number(form.judgeLlmModelId) : null,
            attack_prompt_ids: form.directAttackPromptIds,
          });
        }
        if (form.indirectEnabled && !hasTreeRun) {
          await api.post("/tree-runs", {
            name: `${form.name}-indirect`,
            base_campaign_id: editingId,
            mode: form.indirectMode,
            attempts_per_checkpoint: Number(form.indirectAttemptsPerCheckpoint),
            max_checkpoints: form.indirectMaxCheckpoints ? Number(form.indirectMaxCheckpoints) : null,
            judge_llm_model_id: form.judgeLlmModelId ? Number(form.judgeLlmModelId) : null,
            attack_prompt_ids: form.indirectAttackPromptIds,
          });
        }
      } else {
        const campaign = await api.post<Campaign>("/campaigns", {
          name: form.name,
          session_id: generateSessionId(form.name),
          // status defaults to "new" server-side -- launching (-> active)
          // is a lifecycle action on the list below, not a creation-time choice.
          agent_config_id: form.agent_config_id ? Number(form.agent_config_id) : null,
          interactor_llm_model_id: form.interactor_llm_model_id ? Number(form.interactor_llm_model_id) : null,
          generator_llm_model_id: form.generator_llm_model_id ? Number(form.generator_llm_model_id) : null,
          interactor_persona: needsInteractor ? "benign_user" : null,
          user_instruction: form.user_instruction || null,
        });
        if (form.directEnabled) {
          await api.post("/fuzz-runs", {
            name: `${form.name}-direct`,
            base_campaign_id: campaign.id,
            injection_target: "user_message",
            mode: form.directMode,
            max_iterations: Number(form.directMaxIterations),
            stop_on_success: form.directStopOnSuccess,
            judge_llm_model_id: form.judgeLlmModelId ? Number(form.judgeLlmModelId) : null,
            attack_prompt_ids: form.directAttackPromptIds,
          });
        }
        if (form.indirectEnabled) {
          await api.post("/tree-runs", {
            name: `${form.name}-indirect`,
            base_campaign_id: campaign.id,
            mode: form.indirectMode,
            attempts_per_checkpoint: Number(form.indirectAttemptsPerCheckpoint),
            max_checkpoints: form.indirectMaxCheckpoints ? Number(form.indirectMaxCheckpoints) : null,
            judge_llm_model_id: form.judgeLlmModelId ? Number(form.judgeLlmModelId) : null,
            attack_prompt_ids: form.indirectAttackPromptIds,
          });
        }
      }
      handleCancel();
      load();
    } catch (e) {
      setError(String(e));
    }
  }

  async function setStatus(id: number, status: CampaignStatus) {
    await api.patch(`/campaigns/${id}`, { status });
    load();
  }

  async function handleDelete(id: number) {
    if (!window.confirm("Удалить сканирование? Это действие необратимо.")) return;
    setError(null);
    try {
      await api.delete(`/campaigns/${id}`);
      load();
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div>
      <PageHeader
        title="Сканирования"
        description="Сессия, целевой агент и проверка на уязвимости к prompt-инъекциям — в сообщениях пользователя и в результатах вызовов инструментов."
        actions={
          <button className="btn" onClick={() => (showForm ? handleCancel() : setShowForm(true))}>
            {showForm ? "Отмена" : "Новое сканирование"}
          </button>
        }
      />

      {error && (
        <div className="card" style={{ borderColor: "var(--status-negative)", marginBottom: "1.6rem" }}>
          {error}
        </div>
      )}

      {showForm && (
        <form className="card" onSubmit={handleSubmit} style={{ marginBottom: "2.4rem" }}>
          <h2>{editingId ? "Изменение сканирования" : "Настройка сканирования"}</h2>
          <div style={{ display: "grid", gridTemplateColumns: editingId ? "1fr 1fr" : "1fr", gap: "1.6rem" }}>
            <div className="field">
              <label>Название</label>
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
              />
            </div>
            {editingId && (
              <div className="field">
                <label>ID сессии (нельзя изменить)</label>
                <input value={form.session_id} disabled />
              </div>
            )}
          </div>

          <h3 style={{ marginTop: "2.4rem" }}>Целевой агент</h3>
          <div className="field">
            <label>Конфигурация агента</label>
            <select
              value={form.agent_config_id}
              onChange={(e) => setForm({ ...form, agent_config_id: e.target.value })}
            >
              <option value="">Нет</option>
              {agentConfigs.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </div>

          <h3 style={{ marginTop: "2.4rem" }}>LLM-генератор и судья</h3>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.6rem" }}>
            <div className="field">
              <label>Модель генератора атак</label>
              <select
                value={form.generator_llm_model_id}
                onChange={(e) => setForm({ ...form, generator_llm_model_id: e.target.value })}
              >
                <option value="">Нет</option>
                {llmModels.map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Судья</label>
              <select
                value={form.judgeLlmModelId}
                onChange={(e) => setForm({ ...form, judgeLlmModelId: e.target.value })}
              >
                <option value="">Выберите…</option>
                {llmModels.map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            </div>
          </div>

          {needsInteractor && (
            <>
              <h3 style={{ marginTop: "2.4rem" }}>LLM-интерактор</h3>
              <p style={{ fontSize: 13 }}>
                Агент требует диалога (режим: {interactionModeLabel[selectedAgentConfig?.interaction_mode ?? ""] ?? selectedAgentConfig?.interaction_mode}).
                Интерактор проведёт с ним один базовый диалог от имени обычного пользователя — на основе этого диалога строятся все последующие проверки.
              </p>
              <div className="field">
                <label>Модель интерактора</label>
                <select
                  value={form.interactor_llm_model_id}
                  onChange={(e) => setForm({ ...form, interactor_llm_model_id: e.target.value })}
                >
                  <option value="">Выберите…</option>
                  {llmModels.map((m) => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>Инструкция пользователя</label>
                <textarea
                  rows={2}
                  value={form.user_instruction}
                  onChange={(e) => setForm({ ...form, user_instruction: e.target.value })}
                  placeholder="Попроси ассистента помочь найти книгу о садоводстве и узнать её цену."
                />
              </div>
            </>
          )}

          <h3 style={{ marginTop: "2.4rem" }}>Фаззинг</h3>

          {(editingId && fuzzRunByCampaign.has(editingId)) ? (
            <p style={{ fontSize: 13 }}>
              Прямой фаззинг уже настроен: <Link to={`/fuzz-runs/${fuzzRunByCampaign.get(editingId)!.id}`}>{fuzzRunByCampaign.get(editingId)!.name} →</Link>
            </p>
          ) : (
            <div className="field" style={{ border: "0.1rem solid var(--separator-list)", borderRadius: "var(--radius-m)", padding: "1rem" }}>
              <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <input
                  type="checkbox"
                  checked={form.directEnabled}
                  onChange={(e) => setForm({ ...form, directEnabled: e.target.checked })}
                />
                <strong>Прямая инъекция (в сообщении пользователя)</strong>
              </label>
              {form.directEnabled && (
                <div style={{ marginTop: "0.8rem" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.6rem" }}>
                    <div className="field">
                      <label>Режим</label>
                      <select value={form.directMode} onChange={(e) => setForm({ ...form, directMode: e.target.value as FuzzMode })}>
                        <option value="non_adaptive">{fuzzModeLabel.non_adaptive}</option>
                        <option value="adaptive">{fuzzModeLabel.adaptive}</option>
                      </select>
                    </div>
                    <div className="field">
                      <label>Макс. итераций</label>
                      <input
                        type="number"
                        min={1}
                        value={form.directMaxIterations}
                        onChange={(e) => setForm({ ...form, directMaxIterations: Number(e.target.value) })}
                      />
                    </div>
                  </div>
                  <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, margin: "0.6rem 0" }}>
                    <input
                      type="checkbox"
                      checked={form.directStopOnSuccess}
                      onChange={(e) => setForm({ ...form, directStopOnSuccess: e.target.checked })}
                    />
                    Остановиться при первом успехе
                  </label>
                  <label style={{ fontSize: 13 }}>Техники атак (необязательно — иначе используется набор по умолчанию)</label>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 4 }}>
                    {attackPrompts.map((a) => (
                      <label key={a.id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                        <input
                          type="checkbox"
                          checked={form.directAttackPromptIds.includes(a.id)}
                          onChange={() => toggleAttackPrompt("directAttackPromptIds", a.id)}
                        />
                        <strong>{a.name}</strong>
                        {a.description && <span style={{ color: "var(--text-600)" }}>— {a.description}</span>}
                      </label>
                    ))}
                    {attackPrompts.length === 0 && (
                      <p style={{ fontSize: 12, color: "var(--text-600)" }}>Нет атак — добавьте их на странице «Атаки».</p>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {(editingId && treeRunByCampaign.has(editingId)) ? (
            <p style={{ fontSize: 13 }}>
              Индирект-фаззинг уже настроен: <Link to={`/tree-runs/${treeRunByCampaign.get(editingId)!.id}`}>{treeRunByCampaign.get(editingId)!.name} →</Link>
            </p>
          ) : (
            <div className="field" style={{ border: "0.1rem solid var(--separator-list)", borderRadius: "var(--radius-m)", padding: "1rem", marginTop: "0.8rem" }}>
              <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <input
                  type="checkbox"
                  checked={form.indirectEnabled}
                  onChange={(e) => setForm({ ...form, indirectEnabled: e.target.checked })}
                />
                <strong>Индирект-инъекция (в результате инструмента)</strong>
              </label>
              {form.indirectEnabled && (
                <div style={{ marginTop: "0.8rem" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.6rem" }}>
                    <div className="field">
                      <label>Режим</label>
                      <select value={form.indirectMode} onChange={(e) => setForm({ ...form, indirectMode: e.target.value as FuzzMode })}>
                        <option value="non_adaptive">{fuzzModeLabel.non_adaptive}</option>
                        <option value="adaptive">{fuzzModeLabel.adaptive}</option>
                      </select>
                    </div>
                    <div className="field">
                      <label>Попыток на чекпоинт</label>
                      <input
                        type="number"
                        min={1}
                        value={form.indirectAttemptsPerCheckpoint}
                        onChange={(e) => setForm({ ...form, indirectAttemptsPerCheckpoint: Number(e.target.value) })}
                      />
                    </div>
                  </div>
                  <div className="field">
                    <label>Макс. чекпоинтов (пусто — все найденные)</label>
                    <input
                      value={form.indirectMaxCheckpoints}
                      onChange={(e) => setForm({ ...form, indirectMaxCheckpoints: e.target.value })}
                    />
                  </div>
                  <label style={{ fontSize: 13 }}>Техники атак (необязательно — иначе используется набор по умолчанию)</label>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 4 }}>
                    {attackPrompts.map((a) => (
                      <label key={a.id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                        <input
                          type="checkbox"
                          checked={form.indirectAttackPromptIds.includes(a.id)}
                          onChange={() => toggleAttackPrompt("indirectAttackPromptIds", a.id)}
                        />
                        <strong>{a.name}</strong>
                        {a.description && <span style={{ color: "var(--text-600)" }}>— {a.description}</span>}
                      </label>
                    ))}
                    {attackPrompts.length === 0 && (
                      <p style={{ fontSize: 12, color: "var(--text-600)" }}>Нет атак — добавьте их на странице «Атаки».</p>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          <button className="btn" type="submit" style={{ marginTop: "1.6rem" }}>{editingId ? "Сохранить" : "Создать"}</button>
        </form>
      )}

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <table>
          <thead>
            <tr>
              <th>Название</th>
              <th>Сессия</th>
              <th>Статус</th>
              <th>Фаззинг</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {campaigns.map((c) => (
              <tr key={c.id}>
                <td>
                  <Link to={`/campaigns/${c.id}`}><strong>{c.name}</strong></Link>
                </td>
                <td><code>{c.session_id}</code></td>
                <td>
                  <span className={`badge ${statusBadgeClass[c.status] ?? "badge-neutral"}`}>
                    {statusLabel[c.status] ?? c.status}
                  </span>
                </td>
                <td>
                  <div style={{ display: "flex", gap: 6 }}>
                    {fuzzRunByCampaign.has(c.id) && <span className="badge badge-neutral">прямой</span>}
                    {treeRunByCampaign.has(c.id) && <span className="badge badge-neutral">индирект</span>}
                  </div>
                </td>
                <td>
                  <div style={{ display: "flex", gap: 8 }}>
                    {c.status === "new" && (
                      <button className="btn btn-secondary" onClick={() => setStatus(c.id, "active")}>Запустить</button>
                    )}
                    {c.status === "active" && (
                      <>
                        <button className="btn btn-secondary" onClick={() => setStatus(c.id, "paused")}>Пауза</button>
                        <button className="btn btn-secondary" onClick={() => setStatus(c.id, "cancelled")}>Отменить</button>
                      </>
                    )}
                    {c.status === "paused" && (
                      <>
                        <button className="btn btn-secondary" onClick={() => setStatus(c.id, "active")}>Возобновить</button>
                        <button className="btn btn-secondary" onClick={() => setStatus(c.id, "cancelled")}>Отменить</button>
                      </>
                    )}
                    <button className="btn btn-secondary" onClick={() => handleEdit(c)}>Изменить</button>
                    <button className="btn btn-secondary" onClick={() => handleDelete(c.id)}>Удалить</button>
                    <Link to={`/campaigns/${c.id}`} className="btn btn-secondary">Детали →</Link>
                  </div>
                </td>
              </tr>
            ))}
            {campaigns.length === 0 && (
              <tr>
                <td colSpan={5} style={{ color: "var(--text-600)" }}>Нет сканирований.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
