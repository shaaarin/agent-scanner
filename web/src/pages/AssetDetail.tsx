import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import type { AgentConfig, AssetKind, McpAsset, Scan, SkillAsset } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { ScansTable } from "../components/ScansTable";
import { ScanCreateModal } from "../components/ScanCreateModal";
import { AssetSummary } from "../components/AssetSummary";
import { useAuth } from "../auth/AuthContext";

// Карточка актива: сводка-дашборд (оценка устойчивости и находки),
// реквизиты, кнопка «Новое сканирование» и список сканов этого актива.
// Активы трёх видов читаются из своих эндпоинтов.

const KIND_LABELS: Record<AssetKind, string> = {
  agent: "Агент",
  mcp: "MCP-актив",
  skill: "Skills",
};

// Метки актива: «есть код» (исходники) и «живой сервис» (remote или
// настроенный деплой). У источника с деплоем -- обе.
function assetLabels(kind: AssetKind, agent: AgentConfig | null, mcp: McpAsset | null): { code: boolean; live: boolean } {
  if (kind === "agent") {
    if (agent?.source === "remote") return { code: false, live: true };
    // Деплой настроен, если агент умеет отвечать: порт проброшен или есть
    // режим взаимодействия (api/langgraph).
    const deployConfigured = agent != null && (agent.api_port != null || agent.interaction_mode !== "none");
    return { code: true, live: Boolean(deployConfigured) };
  }
  if (kind === "mcp" && mcp) {
    if (mcp.config.kind === "remote") return { code: false, live: true };
    return { code: true, live: Boolean(mcp.deploy) };
  }
  return { code: true, live: false };
}

function targetSummary(asset: McpAsset): string {
  const config = asset.config;
  if (config.kind === "remote") return String(config.server_url);
  if (config.kind === "repository") return `${config.git_repo_url} (${config.git_ref})`;
  return `MCPB-архив #${config.artifact_id}`;
}

function AgentProps({ asset }: { asset: AgentConfig }) {
  // Remote-агент: репозитория и Dockerfile нет -- важны адрес и настроенный
  // эндпоинт взаимодействия.
  if (asset.source === "remote") {
    const api = (asset.api_config ?? {}) as Record<string, unknown>;
    let endpoint = "—";
    if (asset.interaction_mode === "api") {
      endpoint = `${String(api.method ?? "POST")} ${String(api.url ?? "—")}`;
    } else if (asset.interaction_mode === "langgraph") {
      const langgraph = (asset.langgraph_config ?? {}) as Record<string, unknown>;
      endpoint = String(langgraph.base_url ?? "—");
    }
    return (
      <PropRows
        rows={[
          ["Адрес", asset.remote_base_url ?? "—"],
          ["Взаимодействие", asset.interaction_mode === "none" ? "—" : endpoint],
          ["Назначение", asset.agent_purpose ?? "—"],
        ]}
      />
    );
  }
  return (
    <PropRows
      rows={[
        ["Репозиторий", `${asset.git_repo_url} (${asset.git_ref})`],
        ["Dockerfile", asset.dockerfile_path],
        ["Назначение", asset.agent_purpose ?? "—"],
        ["Режим взаимодействия", asset.interaction_mode],
      ]}
    />
  );
}

function McpProps({ asset }: { asset: McpAsset }) {
  return <PropRows rows={[["Источник", targetSummary(asset)]]} />;
}

function SkillProps({ asset }: { asset: SkillAsset }) {
  return (
    <PropRows
      rows={[
        [
          "Источник",
          asset.source === "zip"
            ? `${asset.archive_filename ?? "архив"} · SHA-256: ${asset.archive_sha256 ?? "—"}`
            : `${asset.git_repo_url ?? "—"} (${asset.git_ref ?? "main"})`,
        ],
      ]}
    />
  );
}

function PropRows({ rows }: { rows: [string, string][] }) {
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
      <tbody>
        {rows.map(([label, value]) => (
          <tr key={label} style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
            <td style={{ padding: "0.6rem 1rem 0.6rem 0", color: "var(--text-500)", width: 220 }}>{label}</td>
            <td style={{ padding: "0.6rem 0", wordBreak: "break-all" }}>{value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function AssetDetail() {
  const { kind, id } = useParams<{ kind: AssetKind; id: string }>();
  const assetKind = (kind ?? "agent") as AssetKind;
  const assetId = Number(id);
  const {canEdit} = useAuth();

  const [agent, setAgent] = useState<AgentConfig | null>(null);
  const [mcp, setMcp] = useState<McpAsset | null>(null);
  const [skill, setSkill] = useState<SkillAsset | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [scansRefreshKey, setScansRefreshKey] = useState(0);

  const loadAsset = useCallback(async () => {
    setNotFound(false);
    try {
      if (assetKind === "agent") setAgent(await api.get<AgentConfig>(`/agent-configs/${assetId}`));
      else if (assetKind === "mcp") setMcp(await api.get<McpAsset>(`/mcp-assets/${assetId}`));
      else if (assetKind === "skill") setSkill(await api.get<SkillAsset>(`/skill-assets/${assetId}`));
      else setNotFound(true);
    } catch {
      setNotFound(true);
    }
  }, [assetKind, assetId]);

  useEffect(() => {
    loadAsset();
  }, [loadAsset]);

  const loadScans = useCallback(
    () => api.get<Scan[]>(`/scans?asset_kind=${assetKind}&asset_id=${assetId}`),
    [assetKind, assetId],
  );

  if (notFound) {
    return (
      <div>
        <PageHeader title="Актив не найден" />
        <div className="card" style={{ padding: "3.2rem", textAlign: "center" }}>
          <p style={{ margin: 0, color: "var(--text-700)" }}>
            Актива с таким идентификатором нет — возможно, он был удалён.
          </p>
        </div>
      </div>
    );
  }

  const assetName = agent?.name ?? mcp?.name ?? skill?.name ?? `#${assetId}`;
  const labels = assetLabels(assetKind, agent, mcp);

  return (
    <div>
      <PageHeader
        title={assetName}
        description={`${KIND_LABELS[assetKind] ?? assetKind} · раздел «Активы»`}
        actions={
          canEdit ? (
            <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
              + Новое сканирование
            </button>
          ) : undefined
        }
      />

      <div style={{ display: "flex", gap: "0.4rem", marginBottom: "1rem" }}>
        {labels.code && <span className="badge badge-neutral">есть код</span>}
        {labels.live && <span className="badge badge-success">живой сервис</span>}
      </div>

      <AssetSummary kind={assetKind} id={assetId} refreshKey={scansRefreshKey} />

      <div className="card" style={{ padding: "1.5rem", marginBottom: "1.5rem" }}>
        {agent && <AgentProps asset={agent} />}
        {mcp && <McpProps asset={mcp} />}
        {skill && <SkillProps asset={skill} />}
      </div>

      <h2 style={{ marginBottom: "1rem" }}>Сканирования актива</h2>
      <ScansTable
        onLoad={loadScans}
        refreshKey={scansRefreshKey}
        emptyTitle="У этого актива пока нет сканирований"
        emptyText="Нажмите «Новое сканирование», чтобы проверить актив."
      />

      {showCreate && (
        <ScanCreateModal
          assetKind={assetKind}
          assetId={assetId}
          assetName={assetName}
          onClose={() => {
            setShowCreate(false);
            setScansRefreshKey((key) => key + 1);
          }}
        />
      )}
    </div>
  );
}
