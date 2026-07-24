import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { InjectionMode, InjectionTarget, InjectionTemplate, SuccessIndicatorField } from "../api/types";
import { PageHeader } from "../components/PageHeader";

const TARGETS: InjectionTarget[] = ["user_message", "tool_result", "assistant_response", "system_prompt"];
const MODES: InjectionMode[] = ["append", "prepend", "replace"];
const FIELDS: SuccessIndicatorField[] = ["tool_name", "tool_arguments", "response_text"];

const emptyForm = {
  name: "",
  description: "",
  target: "user_message" as InjectionTarget,
  mode: "append" as InjectionMode,
  payload: "",
  success_indicator: "",
  success_indicator_field: "tool_name" as SuccessIndicatorField,
  tags: "",
};

export function Templates() {
  const [templates, setTemplates] = useState<InjectionTemplate[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);

  const load = () => api.get<InjectionTemplate[]>("/templates").then(setTemplates).catch((e) => setError(String(e)));

  useEffect(() => {
    load();
  }, []);

  function handleEdit(t: InjectionTemplate) {
    setEditingId(t.id);
    setForm({
      name: t.name,
      description: t.description,
      target: t.target,
      mode: t.mode,
      payload: t.payload,
      success_indicator: t.success_indicator ?? "",
      success_indicator_field: t.success_indicator_field,
      tags: t.tags.join(", "),
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
    const payload = {
      ...form,
      tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
      success_indicator: form.success_indicator || null,
    };
    try {
      if (editingId) {
        await api.put(`/templates/${editingId}`, payload);
      } else {
        await api.post("/templates", payload);
      }
      handleCancel();
      load();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleDelete(id: number) {
    await api.delete(`/templates/${id}`);
    load();
  }

  return (
    <div>
      <PageHeader
        title="Шаблоны инъекций"
        description="Библиотека атакующих payload-ов, которые прокси применяет к целевому элементу: пользовательскому сообщению, результату инструмента, ответу ассистента или системному промпту."
        actions={
          <button className="btn" onClick={() => (showForm ? handleCancel() : setShowForm(true))}>
            {showForm ? "Отмена" : "Новый шаблон"}
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
          <div className="field">
            <label>Описание</label>
            <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)" }}>
            <div className="field">
              <label>Цель инъекции</label>
              <select value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value as InjectionTarget })}>
                {TARGETS.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Режим</label>
              <select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value as InjectionMode })}>
                {MODES.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="field">
            <label>Payload</label>
            <textarea rows={3} value={form.payload} onChange={(e) => setForm({ ...form, payload: e.target.value })} required />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)" }}>
            <div className="field">
              <label>Индикатор успеха (regex)</label>
              <input value={form.success_indicator} onChange={(e) => setForm({ ...form, success_indicator: e.target.value })} />
            </div>
            <div className="field">
              <label>Поле проверки</label>
              <select
                value={form.success_indicator_field}
                onChange={(e) => setForm({ ...form, success_indicator_field: e.target.value as SuccessIndicatorField })}
              >
                {FIELDS.map((f) => (
                  <option key={f} value={f}>{f}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="field">
            <label>Теги (через запятую)</label>
            <input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} />
          </div>
          <button className="btn" type="submit">{editingId ? "Сохранить" : "Создать"}</button>
        </form>
      )}

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <table>
          <thead>
            <tr>
              <th>Название</th>
              <th>Цель</th>
              <th>Режим</th>
              <th>Индикатор успеха</th>
              <th>Теги</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {templates.map((t) => (
              <tr key={t.id}>
                <td>
                  <strong>{t.name}</strong>
                  {t.description && (
                    <div style={{ color: "var(--color-text-muted)", fontSize: 12 }}>{t.description}</div>
                  )}
                </td>
                <td><span className="badge badge-neutral">{t.target}</span></td>
                <td>{t.mode}</td>
                <td><code>{t.success_indicator}</code></td>
                <td>
                  {t.tags.map((tag) => (
                    <span key={tag} className="badge badge-neutral" style={{ marginRight: 4 }}>{tag}</span>
                  ))}
                </td>
                <td style={{ display: "flex", gap: 8 }}>
                  <button className="btn btn-secondary" onClick={() => handleEdit(t)}>Изменить</button>
                  <button className="btn btn-secondary" onClick={() => handleDelete(t.id)}>Удалить</button>
                </td>
              </tr>
            ))}
            {templates.length === 0 && (
              <tr><td colSpan={6} style={{ color: "var(--color-text-muted)" }}>Нет шаблонов.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
