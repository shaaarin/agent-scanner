import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, generatorApi } from "../api/client";
import type { Campaign, FuzzMode, LLMModelListItem, TreeRun } from "../api/types";
import { PageHeader } from "../components/PageHeader";

const emptyForm = {
  name: "",
  base_campaign_id: "",
  mode: "non_adaptive" as FuzzMode,
  max_backbone_turns: 10,
  max_probe_turns: 10,
  max_checkpoints: "",
  attempts_per_checkpoint: 5,
  judge_llm_model_id: "",
};

const statusLabel: Record<string, string> = {
  pending: "не запущен",
  running: "выполняется",
  paused: "на паузе",
  stopped: "остановлен",
  completed: "завершён",
};

const statusBadgeClass: Record<string, string> = {
  running: "badge-warning",
  completed: "badge-success",
  stopped: "badge-danger",
};

export function TreeRuns() {
  const [treeRuns, setTreeRuns] = useState<TreeRun[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [llmModels, setLlmModels] = useState<LLMModelListItem[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = () => {
    api.get<TreeRun[]>("/tree-runs").then(setTreeRuns).catch((e) => setError(String(e)));
    api.get<Campaign[]>("/campaigns").then(setCampaigns);
    api.get<LLMModelListItem[]>("/llm-models").then(setLlmModels);
  };

  useEffect(() => {
    load();
  }, []);

  const campaignById = new Map(campaigns.map((c) => [c.id, c]));

  function handleCancel() {
    setForm(emptyForm);
    setShowForm(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.post("/tree-runs", {
        name: form.name,
        base_campaign_id: Number(form.base_campaign_id),
        mode: form.mode,
        max_backbone_turns: Number(form.max_backbone_turns),
        max_probe_turns: Number(form.max_probe_turns),
        max_checkpoints: form.max_checkpoints ? Number(form.max_checkpoints) : null,
        attempts_per_checkpoint: Number(form.attempts_per_checkpoint),
        judge_llm_model_id: form.judge_llm_model_id ? Number(form.judge_llm_model_id) : null,
      });
      handleCancel();
      load();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleStart(id: number) {
    setError(null);
    setBusyId(id);
    try {
      await generatorApi.post(`/tree/${id}/start`, {});
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyId(null);
    }
  }

  async function handleStop(id: number) {
    setError(null);
    setBusyId(id);
    try {
      await generatorApi.post(`/tree/${id}/stop`, {});
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <PageHeader
        title="Дерево инъекций"
        description="Индирект-фаззинг (tool_result): ведём один реальный, чистый диалог с агентом (backbone), а на каждой точке нового результата инструмента фаззим подмену — несколько попыток до естественного завершения, сравнение с тем, что backbone сделал в этой же точке."
        actions={
          <button className="btn" onClick={() => (showForm ? handleCancel() : setShowForm(true))}>
            {showForm ? "Отмена" : "Новое дерево"}
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
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)" }}>
            <div className="field">
              <label>Название</label>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            </div>
            <div className="field">
              <label>Базовое сканирование (backbone)</label>
              <select
                value={form.base_campaign_id}
                onChange={(e) => setForm({ ...form, base_campaign_id: e.target.value })}
                required
              >
                <option value="">Выберите сканирование…</option>
                {campaigns.map((c) => (
                  <option key={c.id} value={c.id}>{c.name} ({c.session_id})</option>
                ))}
              </select>
            </div>
          </div>
          <p style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: "-0.6rem" }}>
            Сканирование должно быть status=active и injection_rate=0 — backbone-обход должен быть по-настоящему чистым (проверяется на сервере при запуске).
          </p>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)" }}>
            <div className="field">
              <label>Режим мутации</label>
              <select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value as FuzzMode })}>
                <option value="non_adaptive">non_adaptive (ротация операторов мутации)</option>
                <option value="adaptive">adaptive (учитывает недавние неудачи)</option>
              </select>
            </div>
            <div className="field">
              <label>Судья (LLM-модель, опционально)</label>
              <select
                value={form.judge_llm_model_id}
                onChange={(e) => setForm({ ...form, judge_llm_model_id: e.target.value })}
              >
                <option value="">По умолчанию (generator_llm_model_id сканирования)</option>
                {llmModels.map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "var(--space-4)" }}>
            <div className="field">
              <label>Макс. ходов backbone</label>
              <input
                type="number"
                min={1}
                value={form.max_backbone_turns}
                onChange={(e) => setForm({ ...form, max_backbone_turns: Number(e.target.value) })}
              />
            </div>
            <div className="field">
              <label>Макс. ходов попытки</label>
              <input
                type="number"
                min={1}
                value={form.max_probe_turns}
                onChange={(e) => setForm({ ...form, max_probe_turns: Number(e.target.value) })}
              />
            </div>
            <div className="field">
              <label>Попыток на чекпоинт</label>
              <input
                type="number"
                min={1}
                value={form.attempts_per_checkpoint}
                onChange={(e) => setForm({ ...form, attempts_per_checkpoint: Number(e.target.value) })}
              />
            </div>
          </div>
          <div className="field">
            <label>Макс. чекпоинтов (пусто — все найденные)</label>
            <input
              type="number"
              min={1}
              value={form.max_checkpoints}
              onChange={(e) => setForm({ ...form, max_checkpoints: e.target.value })}
            />
          </div>

          <button className="btn" type="submit">Создать</button>
        </form>
      )}

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <table>
          <thead>
            <tr>
              <th>Название</th>
              <th>Сканирование</th>
              <th>Статус</th>
              <th>Попыток/чекпоинт</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {treeRuns.map((t) => (
              <tr key={t.id}>
                <td><Link to={`/tree-runs/${t.id}`}><strong>{t.name}</strong></Link></td>
                <td><code>{campaignById.get(t.base_campaign_id)?.name ?? t.base_campaign_id}</code></td>
                <td>
                  <span className={`badge ${statusBadgeClass[t.status] ?? "badge-neutral"}`}>
                    {statusLabel[t.status] ?? t.status}
                  </span>
                </td>
                <td>{t.attempts_per_checkpoint}</td>
                <td style={{ display: "flex", gap: 8 }}>
                  {(t.status === "pending" || t.status === "paused") && (
                    <button className="btn btn-secondary" disabled={busyId === t.id} onClick={() => handleStart(t.id)}>
                      Запустить
                    </button>
                  )}
                  {t.status === "running" && (
                    <button className="btn btn-secondary" disabled={busyId === t.id} onClick={() => handleStop(t.id)}>
                      Остановить
                    </button>
                  )}
                  <Link to={`/tree-runs/${t.id}`} className="btn btn-secondary">Детали →</Link>
                </td>
              </tr>
            ))}
            {treeRuns.length === 0 && (
              <tr><td colSpan={5} style={{ color: "var(--color-text-muted)" }}>Нет деревьев инъекций.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
