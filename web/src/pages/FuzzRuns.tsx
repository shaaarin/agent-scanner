import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, generatorApi } from "../api/client";
import type { Campaign, FuzzMode, FuzzRun, LLMModelListItem } from "../api/types";
import { PageHeader } from "../components/PageHeader";

const emptyForm = {
  name: "",
  base_campaign_id: "",
  mode: "non_adaptive" as FuzzMode,
  max_iterations: 20,
  stop_on_success: true,
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

export function FuzzRuns() {
  const [fuzzRuns, setFuzzRuns] = useState<FuzzRun[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [llmModels, setLlmModels] = useState<LLMModelListItem[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = () => {
    api.get<FuzzRun[]>("/fuzz-runs").then(setFuzzRuns).catch((e) => setError(String(e)));
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
      await api.post("/fuzz-runs", {
        name: form.name,
        base_campaign_id: Number(form.base_campaign_id),
        injection_target: "user_message",
        mode: form.mode,
        max_iterations: Number(form.max_iterations),
        stop_on_success: form.stop_on_success,
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
      await generatorApi.post(`/fuzz/${id}/start`, {});
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
      await generatorApi.post(`/fuzz/${id}/stop`, {});
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
        title="One-shot фаззинг"
        description="Бандит-driven перебор мутаций InjectionTemplate по одному обмену за раз — только прямая инъекция (user_message). Индикатор успеха: существующий regex-детектор ИЛИ LLM-судья."
        actions={
          <button className="btn" onClick={() => (showForm ? handleCancel() : setShowForm(true))}>
            {showForm ? "Отмена" : "Новый фаззинг"}
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
              <label>Базовое сканирование</label>
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

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)" }}>
            <div className="field">
              <label>Режим</label>
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

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)" }}>
            <div className="field">
              <label>Макс. итераций</label>
              <input
                type="number"
                min={1}
                value={form.max_iterations}
                onChange={(e) => setForm({ ...form, max_iterations: Number(e.target.value) })}
              />
            </div>
            <div className="field" style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginTop: "1.8rem" }}>
              <input
                type="checkbox"
                id="stop_on_success"
                checked={form.stop_on_success}
                onChange={(e) => setForm({ ...form, stop_on_success: e.target.checked })}
              />
              <label htmlFor="stop_on_success" style={{ margin: 0 }}>Остановиться при первом успехе</label>
            </div>
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
              <th>Режим</th>
              <th>Статус</th>
              <th>Итераций</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {fuzzRuns.map((f) => (
              <tr key={f.id}>
                <td><Link to={`/fuzz-runs/${f.id}`}><strong>{f.name}</strong></Link></td>
                <td><code>{campaignById.get(f.base_campaign_id)?.name ?? f.base_campaign_id}</code></td>
                <td>{f.mode}</td>
                <td>
                  <span className={`badge ${statusBadgeClass[f.status] ?? "badge-neutral"}`}>
                    {statusLabel[f.status] ?? f.status}
                  </span>
                </td>
                <td>{f.max_iterations}</td>
                <td style={{ display: "flex", gap: 8 }}>
                  {(f.status === "pending" || f.status === "paused") && (
                    <button className="btn btn-secondary" disabled={busyId === f.id} onClick={() => handleStart(f.id)}>
                      Запустить
                    </button>
                  )}
                  {f.status === "running" && (
                    <button className="btn btn-secondary" disabled={busyId === f.id} onClick={() => handleStop(f.id)}>
                      Остановить
                    </button>
                  )}
                  <Link to={`/fuzz-runs/${f.id}`} className="btn btn-secondary">Детали →</Link>
                </td>
              </tr>
            ))}
            {fuzzRuns.length === 0 && (
              <tr><td colSpan={6} style={{ color: "var(--color-text-muted)" }}>Нет запусков фаззинга.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
