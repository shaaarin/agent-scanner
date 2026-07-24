import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { LLMModelListItem, ProviderType } from "../api/types";
import { PageHeader } from "../components/PageHeader";

const emptyForm = { name: "", provider_type: "openai" as ProviderType, base_url: "", api_key: "", model: "gpt-4o-mini" };

function maskApiKey(raw: string): string {
  if (!raw) return "—";
  const prefix = raw.match(/^[^*]+/)?.[0] ?? "";
  const suffix = raw.match(/[^*]+$/)?.[0] ?? "";
  if (prefix === suffix) return `${prefix}••••`;
  return `${prefix}••••${suffix}`;
}

export function LLMModels() {
  const [llmModels, setLlmModels] = useState<LLMModelListItem[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);

  const load = () => api.get<LLMModelListItem[]>("/llm-models").then(setLlmModels).catch((e) => setError(String(e)));

  useEffect(() => {
    load();
  }, []);

  function handleEdit(m: LLMModelListItem) {
    setEditingId(m.id);
    // api_key intentionally left blank -- the list endpoint only ever
    // returns a masked value, and leaving it blank means "keep unchanged"
    // (see handleSubmit, which omits it from the PUT payload if empty).
    setForm({ name: m.name, provider_type: m.provider_type, base_url: m.base_url, api_key: "", model: m.model });
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
        const { api_key, ...rest } = form;
        await api.put(`/llm-models/${editingId}`, api_key ? form : rest);
      } else {
        await api.post("/llm-models", form);
      }
      handleCancel();
      load();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleDelete(id: number) {
    await api.delete(`/llm-models/${id}`);
    load();
  }

  return (
    <div>
      <PageHeader
        title="LLM-модели"
        description="Подключения к LLM-провайдерам: провайдер, модель, базовый URL и API-ключ. Поддерживается любой провайдер через LiteLLM. Каждое сканирование выбирает отдельную модель для генератора и интерактора."
        actions={
          <button className="btn" onClick={() => (showForm ? handleCancel() : setShowForm(true))}>
            {showForm ? "Отмена" : "Добавить модель"}
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
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 2fr", gap: "var(--space-4)" }}>
            <div className="field">
              <label>Провайдер</label>
              <select value={form.provider_type} onChange={(e) => setForm({ ...form, provider_type: e.target.value as ProviderType })}>
                <option value="openai">openai</option>
                <option value="anthropic">anthropic</option>
              </select>
            </div>
            <div className="field">
              <label>Модель</label>
              <input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} required placeholder="gpt-4o-mini" />
            </div>
            <div className="field">
              <label>Базовый URL</label>
              <input value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} required placeholder="https://api.openai.com" />
            </div>
          </div>
          <div className="field">
            <label>API-ключ{editingId ? " (оставьте пустым, чтобы не менять)" : ""}</label>
            <input
              type="password"
              value={form.api_key}
              onChange={(e) => setForm({ ...form, api_key: e.target.value })}
              required={!editingId}
            />
          </div>
          <button className="btn" type="submit">{editingId ? "Сохранить" : "Создать"}</button>
        </form>
      )}

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <table>
          <thead>
            <tr>
              <th>Название</th>
              <th>Тип</th>
              <th>Модель</th>
              <th>Базовый URL</th>
              <th>API-ключ</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {llmModels.map((m) => (
              <tr key={m.id}>
                <td><strong>{m.name}</strong></td>
                <td><span className="badge badge-neutral">{m.provider_type}</span></td>
                <td><code>{m.model}</code></td>
                <td style={{ color: "var(--text-600)" }}>{m.base_url}</td>
                <td><code>{maskApiKey(m.api_key_masked)}</code></td>
                <td style={{ display: "flex", gap: 8 }}>
                  <button className="btn btn-secondary" onClick={() => handleEdit(m)}>Изменить</button>
                  <button className="btn btn-secondary" onClick={() => handleDelete(m.id)}>Удалить</button>
                </td>
              </tr>
            ))}
            {llmModels.length === 0 && (
              <tr>
                <td colSpan={6} style={{ color: "var(--color-text-muted)" }}>Нет подключений.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
