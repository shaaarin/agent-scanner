import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { AssetKind, Scan, ScannerRegistration } from "../api/types";
import { cleanConfig, initialConfig, isConfigComplete, ScannerConfigForm } from "./ScannerConfigForm";

// Создание сканирования внутри актива: выбор сканера (из GET /scanners,
// отфильтрован по виду актива) и динамическая форма полей из config_schema.
// Никаких настроек сканеров в коде фронта нет.

export function ScanCreateModal({
  assetKind,
  assetId,
  assetName,
  onClose,
}: {
  assetKind: AssetKind;
  assetId: number;
  assetName: string;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const [scanners, setScanners] = useState<ScannerRegistration[]>([]);
  const [selectedType, setSelectedType] = useState<string>("");
  const [scanName, setScanName] = useState("");
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Запрос с контекстом актива: API вернёт available_for_asset и причины
    // неприменимости (вид актива, отсутствие кода/живого сервиса).
    api
      .get<ScannerRegistration[]>(`/scanners?asset_kind=${assetKind}&asset_id=${assetId}`)
      .then((all) => {
        const applicable = all.filter((reg) => reg.asset_kinds.includes(assetKind));
        setScanners(applicable);
        const firstAvailable = applicable.find((reg) => reg.available && reg.available_for_asset !== false);
        if (firstAvailable) {
          setSelectedType(firstAvailable.type);
          setConfig(initialConfig(firstAvailable.config_schema?.fields ?? []));
        }
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoaded(true));
  }, [assetKind, assetId]);

  const selected = useMemo(() => scanners.find((reg) => reg.type === selectedType), [scanners, selectedType]);

  const selectScanner = (type: string) => {
    setSelectedType(type);
    setError(null);
    const reg = scanners.find((item) => item.type === type);
    setConfig(initialConfig(reg?.config_schema?.fields ?? []));
  };

  const create = async (start: boolean) => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const scan = await api.post<Scan>("/scans", {
        name: scanName.trim(),
        type: selected.type,
        asset_kind: assetKind,
        asset_id: assetId,
        session_id: `scan-${crypto.randomUUID()}`,
        config: cleanConfig(selected.config_schema?.fields ?? [], config),
      });
      if (start) {
        await api.post(`/scans/${scan.id}/start`, {});
        navigate(`/scans/${scan.id}`);
      } else {
        onClose();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const fields = selected?.config_schema?.fields ?? [];
  const canCreate =
    Boolean(scanName.trim()) &&
    Boolean(selected?.available) &&
    selected?.available_for_asset !== false &&
    isConfigComplete(fields, config);

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
        padding: "2rem",
      }}
      onClick={onClose}
    >
      <div
        className="card scan-create-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="scan-create-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="scan-create-title" style={{ marginBottom: "0.4rem" }}>Новое сканирование</h2>
        <p style={{ margin: "0 0 1.5rem", color: "var(--text-500)", fontSize: 13 }}>Актив: {assetName}</p>

        {!loaded ? (
          <p style={{ color: "var(--text-500)" }}>Загрузка реестра сканеров…</p>
        ) : scanners.length === 0 ? (
          <p style={{ color: "var(--text-700)" }}>
            Для этого типа актива пока нет подключённых сканеров.
          </p>
        ) : (
          <>
            <div style={{ marginBottom: "1rem" }}>
              <label style={{ display: "block", marginBottom: "0.5rem" }}>Сканер</label>
              <select className="input" style={{ width: "100%" }} value={selectedType} onChange={(e) => selectScanner(e.target.value)}>
                {scanners.map((reg) => {
                  const usable = reg.available && reg.available_for_asset !== false;
                  return (
                    <option key={reg.type} value={reg.type} disabled={!usable}>
                      {reg.name}
                      {!reg.available ? " (сервис недоступен)" : reg.available_for_asset === false ? " (не применим к активу)" : ""}
                    </option>
                  );
                })}
              </select>
              {selected && (
                <p style={{ margin: "0.4rem 0 0", color: "var(--text-500)", fontSize: 13 }}>
                  {selected.available_for_asset === false && selected.unavailable_reason
                    ? `Для этого актива недоступен: ${selected.unavailable_reason}. `
                    : ""}
                  {selected.description}
                </p>
              )}
            </div>

            <div style={{ marginBottom: "1rem" }}>
              <label style={{ display: "block", marginBottom: "0.5rem" }}>
                Название сканирования<span style={{ color: "var(--danger)" }}> *</span>
              </label>
              <input
                type="text"
                className="input"
                style={{ width: "100%" }}
                value={scanName}
                onChange={(e) => setScanName(e.target.value)}
                placeholder="Например: проверка агента поддержки"
              />
            </div>

            {selected && fields.length > 0 && (
              <div style={{ marginBottom: "1rem" }}>
                <ScannerConfigForm fields={fields} value={config} onChange={setConfig} />
              </div>
            )}
          </>
        )}

        {error && (
          <p role="alert" style={{ color: "var(--danger)", fontSize: 13 }}>
            {error}
          </p>
        )}

        <div className="scan-create-actions">
          <button className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Отмена
          </button>
          <button className="btn btn-secondary" onClick={() => create(false)} disabled={busy || !canCreate}>
            {busy ? "Создание…" : "Создать без запуска"}
          </button>
          <button className="btn btn-primary" onClick={() => create(true)} disabled={busy || !canCreate}>
            {busy ? "Запуск…" : "Создать и запустить"}
          </button>
        </div>
      </div>
    </div>
  );
}
