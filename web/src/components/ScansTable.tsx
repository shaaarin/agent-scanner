import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Scan } from "../api/types";
import { displayedScanStatus, scanTypeLabel } from "../api/scanTypes";
import { useAuth } from "../auth/AuthContext";

// Таблица сканов с polling выполняющихся. Используется и на общей странице
// «Сканирования», и в карточке актива: onLoad задаёт источник списка
// (все сканы или сканы актива), emptyText -- подпись пустого состояния.

export function ScanStatusBadge({ status }: { status: string }) {
  const labels: Record<string, string> = {
    pending: "Ожидает запуска",
    running: "Выполняется",
    completed: "Завершено",
    success: "Успешно выполнено",
    partially_failed: "Частично выполнено",
    failed: "Ошибка",
  };
  return <span className={`scan-status scan-status--${status}`}><span>{labels[status] || status}</span></span>;
}

export function ScansTable({
  onLoad,
  emptyTitle,
  emptyText,
  refreshKey = 0,
}: {
  onLoad: () => Promise<Scan[]>;
  emptyTitle: string;
  emptyText: string;
  refreshKey?: number;
}) {
  const navigate = useNavigate();
  const {canEdit, canAdmin} = useAuth();
  const [scans, setScans] = useState<Scan[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<number | null>(null);

  useEffect(() => {
    onLoad().then(setScans).catch((e) => setError(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  useEffect(() => {
    if (!scans.some((scan) => scan.status === "running")) return;
    const timer = setInterval(() => {
      onLoad().then(setScans).catch(() => {});
    }, 2000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scans]);

  const handleStart = async (scanId: number) => {
    setError(null);
    try {
      await api.post(`/scans/${scanId}/start`, {});
      navigate(`/scans/${scanId}`);
    } catch (e) {
      setError(`Не удалось запустить сканирование: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const handleDelete = async (scanId: number) => {
    setError(null);
    try {
      await api.delete(`/scans/${scanId}`);
      setScans(await onLoad());
    } catch (e) {
      setError(`Не удалось удалить сканирование: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const handleRetry = async (scanId: number) => {
    setError(null);
    setRetrying(scanId);
    try {
      const fresh = await api.post<Scan>(`/scans/${scanId}/retry`, {mode: "all"});
      navigate(`/scans/${fresh.id}`);
    } catch (e) {
      setError(`Не удалось повторить сканирование: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setRetrying(null);
    }
  };

  return (
    <div className="card data-table-card">
      {error && (
        <div style={{ padding: "1rem 1.5rem", borderBottom: "0.1rem solid var(--separator-default)" }}>
          <span style={{ color: "var(--danger)" }}>{error}</span>
        </div>
      )}
      {scans.length === 0 ? (
        <div style={{ padding: "3.2rem", textAlign: "center" }}>
          <p style={{ margin: 0, color: "var(--text-700)", fontWeight: 500 }}>{emptyTitle}</p>
          <p style={{ margin: "0.6rem 0 0", color: "var(--text-500)", fontSize: 13 }}>{emptyText}</p>
        </div>
      ) : (
        <table className="data-table data-table--scans" aria-label="Сканирования">
          <colgroup><col /><col /><col /><col /><col /><col /></colgroup>
          <thead>
            <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
              <th scope="col">Название</th>
              <th scope="col">Тип</th>
              <th scope="col">Статус</th>
              <th scope="col">Фаза</th>
              <th scope="col">Создано</th>
              <th scope="col">Действия</th>
            </tr>
          </thead>
          <tbody>
            {scans.map((scan) => (
              <tr key={scan.id} style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                <td data-label="Название"><div className="table-name">
                  <Link className="table-name-link" to={`/scans/${scan.id}`}>
                    {scan.name}
                  </Link>
                  {scan.retry_of_scan_id != null && <div style={{marginTop: "0.4rem", color: "var(--text-600)", fontSize: "0.85rem"}}>Повтор скана №{scan.retry_of_scan_id}</div>}
                </div></td>
                <td data-label="Тип">{scanTypeLabel(scan.type)}</td>
                <td data-label="Статус">
                  <ScanStatusBadge status={displayedScanStatus(scan)} />
                </td>
                <td data-label="Фаза">{scan.phase ?? "—"}</td>
                <td data-label="Создано">{new Date(scan.created_at).toLocaleString("ru-RU")}</td>
                <td data-label="Действия"><div className="row-actions">
                  {canEdit && scan.status === "pending" && (
                    <button
                      className="btn btn-sm btn-primary"
                      onClick={() => handleStart(scan.id)}
                    >
                      Запустить
                    </button>
                  )}
                  {canEdit && ["failed", "partially_failed"].includes(displayedScanStatus(scan)) && <button
                    className="btn btn-sm btn-primary" disabled={retrying !== null}
                    title="Создать и запустить отдельную попытку с теми же настройками"
                    onClick={() => handleRetry(scan.id)}>
                    {retrying === scan.id ? "Запуск…" : "Повторить"}
                  </button>}
                  {canAdmin && <button className="btn btn-sm btn-danger" disabled={scan.status === "running"} onClick={() => handleDelete(scan.id)}>
                    Удалить
                  </button>}
                </div></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
