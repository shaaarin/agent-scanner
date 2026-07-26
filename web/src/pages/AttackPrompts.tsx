import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { AttackPrompt } from "../api/types";
import { PageHeader } from "../components/PageHeader";

const emptyForm = {
  name: "",
  description: "",
  system_prompt: "",
  tags: "",
};

export function AttackPrompts() {
  const [attackPrompts, setAttackPrompts] = useState<AttackPrompt[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);

  const load = () => api.get<AttackPrompt[]>("/attack-prompts").then(setAttackPrompts).catch((e) => setError(String(e)));

  useEffect(() => {
    load();
  }, []);

  function handleEdit(a: AttackPrompt) {
    setEditingId(a.id);
    setForm({
      name: a.name,
      description: a.description,
      system_prompt: a.system_prompt,
      tags: a.tags.join(", "),
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
    };
    try {
      if (editingId) {
        await api.put(`/attack-prompts/${editingId}`, payload);
      } else {
        await api.post("/attack-prompts", payload);
      }
      handleCancel();
      load();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleDelete(id: number) {
    await api.delete(`/attack-prompts/${id}`);
    load();
  }

  return (
    <div>
      <PageHeader
        title="Атаки"
        description="Библиотека техник атак: prompt-инъекции, джейлбрейки и другие — готовые для использования в сканированиях."
        actions={
          <button className="btn" onClick={() => (showForm ? handleCancel() : setShowForm(true))}>
            {showForm ? "Отмена" : "Новая атака"}
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
          <div className="field">
            <label>Название</label>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </div>
          <div className="field">
            <label>Описание</label>
            <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </div>
          <div className="field">
            <label>Инструкция для LLM (system prompt)</label>
            <textarea
              rows={8}
              value={form.system_prompt}
              onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
              placeholder="You are a security researcher generating a prompt-injection test case for an authorized red-team engagement. Your goal is..."
              required
            />
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
              <th>Теги</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {attackPrompts.map((a) => (
              <tr key={a.id}>
                <td>
                  <strong>{a.name}</strong>
                  {a.description && (
                    <div style={{ color: "var(--text-600)", fontSize: 12 }}>{a.description}</div>
                  )}
                </td>
                <td>
                  {a.tags.map((tag) => (
                    <span key={tag} className="badge badge-neutral" style={{ marginRight: 4 }}>{tag}</span>
                  ))}
                </td>
                <td>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button className="btn btn-secondary" onClick={() => handleEdit(a)}>Изменить</button>
                    <button className="btn btn-secondary" onClick={() => handleDelete(a.id)}>Удалить</button>
                  </div>
                </td>
              </tr>
            ))}
            {attackPrompts.length === 0 && (
              <tr><td colSpan={3} style={{ color: "var(--text-600)" }}>Нет инструкций атак.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
