import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Scan } from "../api/types";
import { displayedScanStatus, scanTypeLabel } from "../api/scanTypes";

// Таблица сканов с polling выполняющихся. Используется и на общей странице
// «Сканирования», и в карточке актива: onLoad задаёт источник списка
// (все сканы или сканы актива), emptyText -- подпись пустого состояния.

export function ScanStatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: "badge-secondary",
    running: "badge-primary",
    completed: "badge-success",
    success: "badge-success",
    partially_failed: "badge-warning",
    failed: "badge-danger",
  };
  const labels: Record<string, string> = {
    pending: "Ожидает запуска",
    running: "Выполняется",
    completed: "Завершено",
    success: "Успешно выполнено",
    partially_failed: "Частично выполнено",
    failed: "Ошибка",
  };
  return <span className={`badge ${colors[status] || "badge-secondary"}`}>{labels[status] || status}</span>;
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
    <div className="card">
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
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
              <th style={{ padding: "1rem", textAlign: "left", width: "100%" }}>Название</th>
              <th style={{ padding: "1rem", textAlign: "left" }}>Тип</th>
              <th style={{ padding: "1rem", textAlign: "left" }}>Статус</th>
              <th style={{ padding: "1rem", textAlign: "left" }}>Фаза</th>
              <th style={{ padding: "1rem", textAlign: "left" }}>Создано</th>
              <th style={{ padding: "1rem", textAlign: "right" }}>Действия</th>
            </tr>
          </thead>
          <tbody>
            {scans.map((scan) => (
              <tr key={scan.id} style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                <td style={{ padding: "1rem" }}>
                  <button className="btn btn-sm btn-secondary" onClick={() => navigate(`/scans/${scan.id}`)}>
                    {scan.name}
                  </button>
                  {scan.retry_of_scan_id != null && <div style={{marginTop: "0.4rem", color: "var(--text-600)", fontSize: "0.85rem"}}>Повтор скана №{scan.retry_of_scan_id}</div>}
                </td>
                <td style={{ padding: "1rem" }}>{scanTypeLabel(scan.type)}</td>
                <td style={{ padding: "1rem" }}>
                  <ScanStatusBadge status={displayedScanStatus(scan)} />
                </td>
                <td style={{ padding: "1rem" }}>{scan.phase ?? "—"}</td>
                <td style={{ padding: "1rem" }}>{new Date(scan.created_at).toLocaleString("ru-RU")}</td>
                <td style={{ padding: "1rem", textAlign: "right" }}>
                  {scan.status === "pending" && (
                    <button
                      className="btn btn-sm btn-primary"
                      onClick={() => handleStart(scan.id)}
                      style={{ marginRight: "0.5rem" }}
                    >
                      Запустить
                    </button>
                  )}
                  {["failed", "partially_failed"].includes(displayedScanStatus(scan)) && <button
                    className="btn btn-sm btn-primary" disabled={retrying !== null}
                    title="Создать и запустить отдельную попытку с теми же настройками"
                    onClick={() => handleRetry(scan.id)} style={{marginRight: "0.5rem"}}>
                    {retrying === scan.id ? "Запуск…" : "Повторить"}
                  </button>}
                  <button className="btn btn-sm btn-danger" disabled={scan.status === "running"} onClick={() => handleDelete(scan.id)}>
                    Удалить
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
