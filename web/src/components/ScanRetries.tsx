import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Scan, ScanRetryMode, ScanRetryOptions } from "../api/types";
import { ScanStatusBadge } from "./ScansTable";

const modeLabels = {all: "Весь скан", failed: "Незавершённые движки", engine: "Отдельный движок"};

export function ScanRetries({scan}: {scan: Scan}) {
  const navigate = useNavigate();
  const [options, setOptions] = useState<ScanRetryOptions | null>(null);
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const fresh = await api.get<ScanRetryOptions>(`/scans/${scan.id}/retries`);
        if (!cancelled) { setOptions(fresh); setLoadError(null); }
      } catch (e) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : String(e));
      }
    };
    void load();
    const timer = setInterval(load, 2000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [scan.id, scan.status]);

  const retry = async (mode: ScanRetryMode, engine_id?: string) => {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError(null);
    try {
      const fresh = await api.post<Scan>(`/scans/${scan.id}/retry`, {mode, engine_id});
      navigate(`/scans/${fresh.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  };

  return <section className="card" style={{marginBottom: "2rem"}} aria-label="Повторные запуски">
    <h3>Повторные запуски</h3>
    <p>Каждый повтор создаёт отдельный скан со своим журналом и результатами. Предыдущие отчёты сохраняются.</p>
    {scan.type === "mcp" && <p>Используются цель и настройки из этого скана. Результаты отдельного движка не заменяют отчёт всего набора.</p>}
    {loadError && <p role="alert">Не удалось обновить историю: {loadError}</p>}
    {error && <p role="alert" style={{color: "var(--danger)"}}>Не удалось повторить скан: {error}</p>}
    {!options && !loadError && <p>Загрузка доступных действий…</p>}
    {options && <>
      {options.active_scan_id !== null && options.active_scan_id !== scan.id && <p role="status">
        В этой истории уже ожидает запуска или выполняется <Link to={`/scans/${options.active_scan_id}`}>скан №{options.active_scan_id}</Link>.
      </p>}
      <div style={{display: "flex", flexWrap: "wrap", gap: "0.8rem"}}>
        {options.can_retry_all && <button className="btn btn-primary" disabled={busy || !!loadError} onClick={() => retry("all")}>
          {busy ? "Запуск…" : "Повторить весь скан"}
        </button>}
        {options.can_retry_failed && <button className="btn btn-secondary" disabled={busy || !!loadError} onClick={() => retry("failed")}>
          Повторить незавершённые движки
        </button>}
      </div>
      {options.engines.length > 0 && <>
        <h4 style={{marginTop: "1.5rem"}}>Повторить отдельный движок</h4>
        <ul style={{listStyle: "none", padding: 0, margin: 0, display: "grid", gap: "0.8rem"}}>
          {options.engines.map(engine => <li key={engine.id} style={{display: "flex", alignItems: "center", flexWrap: "wrap", gap: "0.8rem"}}>
            <span>{engine.name}</span>
            {engine.status === "pending" ? <span className="badge badge-secondary">Нет окончательного результата</span> : <ScanStatusBadge status={engine.status} />}
            <button className="btn btn-sm btn-secondary" disabled={busy || !!loadError} onClick={() => retry("engine", engine.id)} aria-label={`Повторить движок ${engine.name}`}>
              Повторить
            </button>
          </li>)}
        </ul>
      </>}
      {options.attempts.length > 1 && <>
        <h4 style={{marginTop: "1.5rem"}}>История попыток</h4>
        <ol style={{paddingLeft: "1.5rem"}}>
          {options.attempts.map(attempt => <li key={attempt.id} style={{margin: "0.8rem 0"}}>
            {attempt.id === scan.id ? <strong>Скан №{attempt.id} (открыт)</strong> : <Link to={`/scans/${attempt.id}`}>Скан №{attempt.id}</Link>}
            {" · "}{attempt.retry_mode ? modeLabels[attempt.retry_mode] : "Исходный запуск"}{" · "}
            <ScanStatusBadge status={attempt.status} />{" · "}{new Date(attempt.created_at).toLocaleString("ru-RU")}
            {attempt.retry_of_scan_id !== null && <> · повтор <Link to={`/scans/${attempt.retry_of_scan_id}`}>№{attempt.retry_of_scan_id}</Link></>}
          </li>)}
        </ol>
      </>}
    </>}
  </section>;
}
