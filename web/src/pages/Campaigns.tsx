import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type {
  AgentConfig,
  Campaign,
  CampaignStatus,
  InjectionTemplate,
  LLMModelListItem,
} from "../api/types";
import { PageHeader } from "../components/PageHeader";

const emptyForm = {
  name: "",
  session_id: "",
  template_id: "",
  status: "paused" as CampaignStatus,
  injection_rate: 1,
  agent_config_id: "",
  interactor_llm_model_id: "",
  generator_llm_model_id: "",
  user_instruction: "",
};

const statusLabel: Record<string, string> = {
  active: "активно",
  paused: "на паузе",
};

export function Campaigns() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [templates, setTemplates] = useState<InjectionTemplate[]>([]);
  const [llmModels, setLlmModels] = useState<LLMModelListItem[]>([]);
  const [agentConfigs, setAgentConfigs] = useState<AgentConfig[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);

  const load = () => {
    api.get<Campaign[]>("/campaigns").then(setCampaigns).catch((e) => setError(String(e)));
    api.get<InjectionTemplate[]>("/templates").then(setTemplates);
    api.get<LLMModelListItem[]>("/llm-models").then(setLlmModels);
    api.get<AgentConfig[]>("/agent-configs").then(setAgentConfigs);
  };

  useEffect(() => {
    load();
  }, []);

  const agentConfigId = form.agent_config_id ? Number(form.agent_config_id) : null;
  const selectedAgentConfig = agentConfigs.find((a) => a.id === agentConfigId);
  const needsInteractor = selectedAgentConfig && selectedAgentConfig.interaction_mode !== "none";

  function handleEdit(c: Campaign) {
    setEditingId(c.id);
    setForm({
      name: c.name,
      session_id: c.session_id,
      template_id: String(c.template_id),
      status: c.status,
      injection_rate: c.injection_rate,
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
    try {
      if (editingId) {
        // session_id/template_id are immutable once a campaign exists (tied
        // to the k8s namespace/proxy session) -- CampaignUpdate doesn't
        // accept them, so they're intentionally left out here.
        await api.patch(`/campaigns/${editingId}`, {
          name: form.name,
          status: form.status,
          injection_rate: Number(form.injection_rate),
          agent_config_id: form.agent_config_id ? Number(form.agent_config_id) : null,
          interactor_llm_model_id: form.interactor_llm_model_id ? Number(form.interactor_llm_model_id) : null,
          generator_llm_model_id: form.generator_llm_model_id ? Number(form.generator_llm_model_id) : null,
          interactor_persona: needsInteractor ? "benign_user" : null,
          user_instruction: form.user_instruction || null,
        });
      } else {
        await api.post("/campaigns", {
          name: form.name,
          session_id: form.session_id,
          template_id: Number(form.template_id),
          status: form.status,
          injection_rate: Number(form.injection_rate),
          agent_config_id: form.agent_config_id ? Number(form.agent_config_id) : null,
          interactor_llm_model_id: form.interactor_llm_model_id ? Number(form.interactor_llm_model_id) : null,
          generator_llm_model_id: form.generator_llm_model_id ? Number(form.generator_llm_model_id) : null,
          interactor_persona: needsInteractor ? "benign_user" : null,
          user_instruction: form.user_instruction || null,
        });
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

  return (
    <div>
      <PageHeader
        title="Сканирования"
        description="Сканирование — это кампания: шаблон инъекции, привязанный к сессии, с опциональной конфигурацией агента и LLM-моделями для интерактора и генератора атак."
        actions={
          <button className="btn" onClick={() => (showForm ? handleCancel() : setShowForm(true))}>
            {showForm ? "Отмена" : "Новое сканирование"}
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
          <h2>{editingId ? "Изменение сканирования" : "Настройка сканирования"}</h2>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)" }}>
            <div className="field">
              <label>Название</label>
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
              />
            </div>
            <div className="field">
              <label>ID сессии{editingId ? " (нельзя изменить)" : ""}</label>
              <input
                value={form.session_id}
                onChange={(e) => setForm({ ...form, session_id: e.target.value })}
                placeholder="например: scan-2026-07-18-01"
                required
                disabled={!!editingId}
              />
            </div>
          </div>

          <div className="field">
            <label>Шаблон инъекции{editingId ? " (нельзя изменить)" : ""}</label>
            <select
              value={form.template_id}
              onChange={(e) => setForm({ ...form, template_id: e.target.value })}
              required
              disabled={!!editingId}
            >
              <option value="">Выберите шаблон…</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>{t.name} ({t.target})</option>
              ))}
            </select>
          </div>

          <h3 style={{ marginTop: "var(--space-5)" }}>Целевой агент</h3>
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

          <h3 style={{ marginTop: "var(--space-5)" }}>LLM-генератор</h3>
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

          {needsInteractor && (
            <>
              <h3 style={{ marginTop: "var(--space-5)" }}>LLM-интерактор</h3>
              <p style={{ fontSize: 13 }}>
                Агент требует взаимодействия ({selectedAgentConfig?.interaction_mode}). Интерактор эмулирует легитимного пользователя — укажите инструкцию для его поведения.
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

          <h3 style={{ marginTop: "var(--space-5)" }}>Параметры запуска</h3>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)" }}>
            <div className="field">
              <label>Доля инъекций (0–1)</label>
              <input
                type="number"
                min={0}
                max={1}
                step={0.1}
                value={form.injection_rate}
                onChange={(e) => setForm({ ...form, injection_rate: Number(e.target.value) })}
              />
            </div>
            <div className="field">
              <label>Начальный статус</label>
              <select
                value={form.status}
                onChange={(e) => setForm({ ...form, status: e.target.value as CampaignStatus })}
              >
                <option value="paused">на паузе</option>
                <option value="active">активно</option>
              </select>
            </div>
          </div>

          <button className="btn" type="submit">{editingId ? "Сохранить" : "Создать"}</button>
        </form>
      )}

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <table>
          <thead>
            <tr>
              <th>Название</th>
              <th>Сессия</th>
              <th>Статус</th>
              <th>Доля инъекций</th>
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
                  <span className={`badge ${c.status === "active" ? "badge-success" : "badge-neutral"}`}>
                    {statusLabel[c.status] ?? c.status}
                  </span>
                </td>
                <td>{c.injection_rate}</td>
                <td style={{ display: "flex", gap: 8 }}>
                  {c.status !== "active" && (
                    <button className="btn btn-secondary" onClick={() => setStatus(c.id, "active")}>Запустить</button>
                  )}
                  {c.status === "active" && (
                    <button className="btn btn-secondary" onClick={() => setStatus(c.id, "paused")}>Остановить</button>
                  )}
                  <button className="btn btn-secondary" onClick={() => handleEdit(c)}>Изменить</button>
                  <Link to={`/campaigns/${c.id}`} className="btn btn-secondary">Детали →</Link>
                </td>
              </tr>
            ))}
            {campaigns.length === 0 && (
              <tr>
                <td colSpan={5} style={{ color: "var(--color-text-muted)" }}>Нет сканирований.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
