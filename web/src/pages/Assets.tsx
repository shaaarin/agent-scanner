import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, launcherApi } from "../api/client";
import type {
  AssetKind,
  McpAsset,
  MCPArtifact,
  MCPTargetKind,
  MCPTransport,
  SkillAsset,
} from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { AgentConfigs } from "./AgentConfigs";
import { AssetActions } from "../components/AssetActions";
import { McpAssetEditor } from "../components/McpAssetEditor";

// Раздел «Активы»: агенты / MCP / skills. Актив -- сущность, внутри которой
// создаются сканирования (см. AssetDetail). Вкладка «Агенты» переиспользует
// существующую страницу конфигураций агентов целиком.

const TABS: { key: AssetKind; label: string }[] = [
  { key: "agent", label: "Агенты" },
  { key: "mcp", label: "MCP" },
  { key: "skill", label: "Skills" },
];

export function Assets() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as AssetKind) || "agent";

  return (
    <div>
      <PageHeader
        title="Активы"
        description="То, что вы проверяете: агенты, MCP-серверы и skills. Выберите актив, чтобы создать для него сканирование."
      />
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginBottom: "1.5rem" }}>
        {TABS.map((item) => (
          <button
            key={item.key}
            className={`btn ${tab === item.key ? "btn-primary" : "btn-secondary"}`}
            onClick={() => setParams({ tab: item.key })}
          >
            {item.label}
          </button>
        ))}
      </div>
      {tab === "agent" && <AgentConfigs />}
      {tab === "mcp" && <McpAssetsTab />}
      {tab === "skill" && <SkillsAssetsTab />}
    </div>
  );
}

const TARGET_KIND_LABELS: Record<string, string> = {
  remote: "Удалённый сервер",
  repository: "Git-репозиторий",
  bundle: "MCPB-архив",
};

// Метки актива: «есть код» (исходники для SAST) и «живой сервис» (куда
// можно идти напрямую или настроен деплой для динамики).
function mcpAssetLabels(asset: McpAsset): { code: boolean; live: boolean } {
  const kind = asset.config.kind;
  if (kind === "remote") return { code: false, live: true };
  return { code: true, live: Boolean(asset.deploy) };
}

function AssetLabels({ labels }: { labels: { code: boolean; live: boolean } }) {
  return (
    <span className="asset-labels">
      {labels.code && <span className="badge badge-neutral">есть код</span>}
      {labels.live && <span className="badge badge-success">живой сервис</span>}
    </span>
  );
}

function repoNameFromUrl(url: string): string {
  const match = url.match(/([^/]+?)(\.git)?\/?$/);
  return (match?.[1] ?? "mcp").replace(/\W+/g, "-").toLowerCase();
}

function McpAssetsTab() {
  const [assets, setAssets] = useState<McpAsset[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<McpAsset | null>(null);

  const load = () => api.get<McpAsset[]>("/mcp-assets").then(setAssets).catch((e) => setError(String(e)));
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleDelete = async (id: number) => {
    setError(null);
    try {
      await api.delete(`/mcp-assets/${id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div>
      <div className="section-heading">
        <h2 style={{ margin: 0 }}>MCP-активы</h2>
        <button className="btn" onClick={() => {setEditing(null); setShowForm(!showForm);}}>
          {showForm ? "Отмена" : "+ Добавить MCP-актив"}
        </button>
      </div>
      {error && (
        <div className="card" style={{ padding: "1rem 1.5rem", marginBottom: "1rem", borderLeft: "0.3rem solid var(--danger)" }}>
          <span style={{ color: "var(--danger)" }}>{error}</span>
        </div>
      )}
      {showForm && (
        <McpAssetWizard
          onCreated={() => {
            setShowForm(false);
            load();
          }}
        />
      )}
      {editing && <McpAssetEditor key={editing.id} asset={editing} onCancel={() => setEditing(null)} onSaved={() => {setEditing(null); load();}} />}
      <div className="card data-table-card">
        {assets.length === 0 ? (
          <div style={{ padding: "3.2rem", textAlign: "center" }}>
            <p style={{ margin: 0, color: "var(--text-700)", fontWeight: 500 }}>Пока нет ни одного MCP-актива</p>
            <p style={{ margin: "0.6rem 0 0", color: "var(--text-500)", fontSize: 13 }}>
              Добавьте MCP-сервер, репозиторий или MCPB-архив, чтобы проверять его безопасность.
            </p>
          </div>
        ) : (
          <table className="data-table data-table--assets" aria-label="MCP-активы">
            <colgroup><col /><col /><col /><col /></colgroup>
            <thead>
              <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                <th scope="col">Название</th>
                <th scope="col">Источник</th>
                <th scope="col">Создан</th>
                <th scope="col">Действия</th>
              </tr>
            </thead>
            <tbody>
              {assets.map((asset) => (
                <tr key={asset.id} style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                  <td data-label="Название">
                    <div className="table-name">
                    <Link className="table-name-link" to={`/assets/mcp/${asset.id}`}>
                      {asset.name}
                    </Link>
                    <AssetLabels labels={mcpAssetLabels(asset)} />
                    {asset.description && (
                      <div style={{ color: "var(--text-500)", fontSize: 12, marginTop: "0.3rem" }}>{asset.description}</div>
                    )}
                    </div>
                  </td>
                  <td data-label="Источник">
                    <span>{TARGET_KIND_LABELS[asset.config.kind] ?? asset.config.kind}</span>
                  </td>
                  <td data-label="Создан">{new Date(asset.created_at).toLocaleString("ru-RU")}</td>
                  <td data-label="Действия">
                    <AssetActions onEdit={() => {setShowForm(false); setError(null); setEditing(asset);}} onDelete={() => handleDelete(asset.id)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

type EnvRow = { key: string; value: string };

// Инлайн-визард создания MCP-актива (как у агентов, без модального окна).
// Для Git-источника -- тот же поток, что у агентов: URL + токен ->
// «Загрузить репозиторий» (клонирование через launcher) -> выбор ветки из
// доступных -> настройка. Дальше либо «Создать актив», либо «Настроить
// деплой» (Dockerfile, порт, URL path к MCP; взаимодействие всегда по
// MCP-протоколу, поэтому выбора режима нет). MCPB -- загрузка архива,
// деплой опционален. Удалённый сервер -- один шаг.
function McpAssetWizard({ onCreated }: { onCreated: () => void }) {
  const [step, setStep] = useState<"source" | "repo" | "deploy">("source");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [targetKind, setTargetKind] = useState<MCPTargetKind>("remote");
  const [serverUrl, setServerUrl] = useState("");
  const [transport, setTransport] = useState<MCPTransport>("auto");
  const [bearerToken, setBearerToken] = useState("");
  const [headerRows, setHeaderRows] = useState<EnvRow[]>([{ key: "", value: "" }]);
  const [verifyTls, setVerifyTls] = useState(true);
  const [gitRepoUrl, setGitRepoUrl] = useState("");
  const [gitAccessToken, setGitAccessToken] = useState("");
  const [branches, setBranches] = useState<string[]>([]);
  const [gitRef, setGitRef] = useState("main");
  const [dockerfiles, setDockerfiles] = useState<string[]>([]);

  const [bundleSource, setBundleSource] = useState<"upload" | "url">("upload");
  const [bundleFile, setBundleFile] = useState<File | null>(null);
  const [bundleUrl, setBundleUrl] = useState("");
  const [bundleExpectedSha, setBundleExpectedSha] = useState("");
  const [bundleUserConfig, setBundleUserConfig] = useState("{}");
  const [artifact, setArtifact] = useState<MCPArtifact | null>(null);
  const [artifactUploading, setArtifactUploading] = useState(false);
  const [artifactError, setArtifactError] = useState<string | null>(null);
  const [loadingRepo, setLoadingRepo] = useState(false);
  const [inspecting, setInspecting] = useState(false);
  const [deployPort, setDeployPort] = useState("");
  const [deployDockerfile, setDeployDockerfile] = useState("Dockerfile");
  const [deployMcpPath, setDeployMcpPath] = useState("/mcp");
  const [deployEnvRows, setDeployEnvRows] = useState<EnvRow[]>([{ key: "", value: "" }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const updateDeployEnvRow = (i: number, field: "key" | "value", value: string) => {
    setDeployEnvRows((rows) => rows.map((r, idx) => (idx === i ? { ...r, [field]: value } : r)));
  };

  const updateHeaderRow = (i: number, field: "key" | "value", value: string) => {
    setHeaderRows((rows) => rows.map((r, idx) => (idx === i ? { ...r, [field]: value } : r)));
  };

  const rowsToMap = (rows: EnvRow[]): Record<string, string> =>
    Object.fromEntries(rows.filter((r) => r.key.trim()).map((r) => [r.key.trim(), r.value]));

  const inspectRepo = async (ref: string) => {
    setInspecting(true);
    setError(null);
    try {
      const result = await launcherApi.post<{ dockerfiles: string[] }>("/repo/inspect", {
        git_repo_url: gitRepoUrl,
        git_ref: ref,
        git_access_token: gitAccessToken || null,
      });
      setDockerfiles(result.dockerfiles);
      setDeployDockerfile(result.dockerfiles[0] ?? "Dockerfile");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setInspecting(false);
    }
  };

  // «Клонирование»: launcher отдаёт доступные ветки, затем инспектируем
  // дефолтную (Dockerfile для деплоя). Сам код здесь не запускается.
  const handleLoadRepo = async () => {
    setError(null);
    setLoadingRepo(true);
    try {
      const result = await launcherApi.post<{ branches: string[] }>("/repo/branches", {
        git_repo_url: gitRepoUrl,
        git_access_token: gitAccessToken || null,
      });
      setBranches(result.branches);
      const defaultBranch = result.branches[0];
      setGitRef(defaultBranch);
      setStep("repo");
      await inspectRepo(defaultBranch);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingRepo(false);
    }
  };

  const handleBranchChange = async (ref: string) => {
    setGitRef(ref);
    await inspectRepo(ref);
  };

  const handleUploadBundle = async () => {
    setArtifactError(null);
    setArtifactUploading(true);
    try {
      let uploaded: MCPArtifact;
      if (bundleSource === "upload") {
        if (!bundleFile) throw new Error("Выберите MCPB-файл");
        const formData = new FormData();
        formData.append("file", bundleFile);
        uploaded = await api.postForm<MCPArtifact>("/mcp-artifacts/upload", formData);
      } else {
        if (!bundleUrl.trim()) throw new Error("Укажите HTTPS URI MCPB-архива");
        uploaded = await api.post<MCPArtifact>("/mcp-artifacts/from-url", {
          url: bundleUrl.trim(),
          expected_sha256: bundleExpectedSha.trim() || null,
        });
      }
      setArtifact(uploaded);
    } catch (e) {
      setArtifact(null);
      setArtifactError(e instanceof Error ? e.message : String(e));
    } finally {
      setArtifactUploading(false);
    }
  };

  // Название не блокирует шаг: если не задано -- генерируем из источника.
  const sourceReady =
    targetKind === "remote"
      ? Boolean(serverUrl.trim())
      : targetKind === "repository"
        ? branches.length > 0
        : Boolean(artifact);

  const buildTarget = (): Record<string, unknown> => {
    if (targetKind === "remote") {
      const parsedHeaders = rowsToMap(headerRows);
      if (bearerToken.trim()) parsedHeaders.Authorization = `Bearer ${bearerToken.trim()}`;
      return { kind: "remote", server_url: serverUrl.trim(), transport, headers: parsedHeaders, verify_tls: verifyTls };
    }
    if (targetKind === "repository") {
      return {
        kind: "repository",
        git_repo_url: gitRepoUrl.trim(),
        git_ref: gitRef.trim(),
        git_access_token: gitAccessToken.trim() || null,
      };
    }
    if (!artifact) throw new Error("Сначала загрузите MCPB-архив");
    const userConfig: unknown = JSON.parse(bundleUserConfig || "{}");
    if (!userConfig || typeof userConfig !== "object" || Array.isArray(userConfig)) {
      throw new Error("Пользовательская конфигурация MCPB должна быть JSON-объектом");
    }
    return { kind: "bundle", artifact_id: artifact.id, user_config: userConfig };
  };

  // Деплой задаётся только для Git/MCPB; пустой блок -> null.
  const buildDeploy = () => {
    if (targetKind === "remote") return null;
    const env = rowsToMap(deployEnvRows);
    const hasAny = Boolean(deployPort.trim() || deployMcpPath.trim() || (targetKind === "repository" && deployDockerfile.trim()) || Object.keys(env).length);
    return hasAny
      ? {
          ...(deployPort.trim() && { port: Number(deployPort) }),
          ...(targetKind === "repository" && deployDockerfile.trim() && { dockerfile_path: deployDockerfile.trim() }),
          ...(deployMcpPath.trim() && { mcp_path: deployMcpPath.trim() }),
          env,
        }
      : null;
  };

  const resolvedName = () => {
    if (name.trim()) return name.trim();
    const suffix = Math.random().toString(36).slice(2, 6);
    if (targetKind === "bundle" && artifact) return `${artifact.original_filename.replace(/\.mcpb$/i, "")}-${suffix}`;
    if (targetKind === "repository" && gitRepoUrl.trim()) return `${repoNameFromUrl(gitRepoUrl.trim())}-${suffix}`;
    return `${serverUrl.replace(/^https?:\/\//, "").replace(/\W+/g, "-").slice(0, 40)}-${suffix}`;
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post<McpAsset>("/mcp-assets", {
        name: resolvedName(),
        description: description.trim() || null,
        config: buildTarget(),
        deploy: buildDeploy(),
      });
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const nameField = (
    <>
      <div className="field">
        <label>Название · необязательно, иначе сгенерируем из источника</label>
        <input className="input" style={{ width: "100%" }} value={name} onChange={(e) => setName(e.target.value)} placeholder="Например: MCP-сервер поиска" />
      </div>
      <div className="field">
        <label>Описание</label>
        <input className="input" style={{ width: "100%" }} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Необязательно" />
      </div>
    </>
  );

  if (step === "source") {
    return (
      <div className="card" style={{ marginBottom: "2.4rem" }}>
        <h2 style={{ marginTop: 0 }}>Шаг 1. Источник</h2>
        <p style={{ fontSize: 13, color: "var(--text-500)", margin: "0 0 1.6rem" }}>
          {targetKind === "remote"
            ? "Работающий MCP-сервер: укажите адрес — проверки пойдут напрямую."
            : targetKind === "repository"
              ? "Укажите git URL и токен — платформа склонирует репозиторий и покажет доступные ветки."
              : "Загрузите MCPB-архив — платформа проверит его и передаст исходники в SAST."}
        </p>
        {nameField}
        <div className="field">
          <label>Источник MCP-сервера</label>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            {([
              ["remote", "Удалённый сервер"],
              ["repository", "Git-репозиторий"],
              ["bundle", "MCPB-архив"],
            ] as [MCPTargetKind, string][]).map(([kind, label]) => (
              <button key={kind} type="button" className={`btn ${targetKind === kind ? "btn-primary" : "btn-secondary"}`} onClick={() => setTargetKind(kind)}>
                {label}
              </button>
            ))}
          </div>
        </div>

        {targetKind === "remote" && (
          <>
            <div className="field">
              <label>Адрес MCP-сервера</label>
              <input type="url" className="input" style={{ width: "100%" }} value={serverUrl} onChange={(e) => setServerUrl(e.target.value)} placeholder="https://example.com/mcp" />
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.6rem" }}>
              <div className="field">
                <label>Транспорт MCP</label>
                <select className="input" style={{ width: "100%" }} value={transport} onChange={(e) => setTransport(e.target.value as MCPTransport)}>
                  <option value="auto">Автоопределение</option>
                  <option value="streamable_http">Streamable HTTP</option>
                  <option value="sse">Legacy SSE</option>
                </select>
              </div>
              <div className="field">
                <label>Bearer Token</label>
                <input type="password" className="input" style={{ width: "100%" }} value={bearerToken} onChange={(e) => setBearerToken(e.target.value)} placeholder="Необязательно" autoComplete="off" />
              </div>
            </div>
            <div className="field">
              <label>Дополнительные заголовки · имя + значение</label>
              {headerRows.map((row, i) => (
                <div key={i} style={{ display: "flex", gap: 8, marginBottom: 8 }}>
                  <input placeholder="X-API-Key" value={row.key} onChange={(e) => updateHeaderRow(i, "key", e.target.value)} />
                  <input placeholder="значение" value={row.value} onChange={(e) => updateHeaderRow(i, "value", e.target.value)} autoComplete="off" />
                </div>
              ))}
              <button type="button" className="btn btn-secondary" onClick={() => setHeaderRows((r) => [...r, { key: "", value: "" }])}>
                + Добавить заголовок
              </button>
              <p style={{ margin: "0.4rem 0 0", fontSize: 12, color: "var(--text-500)" }}>Уходят с каждым запросом к серверу. Bearer Token будет добавлен как Authorization.</p>
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "1rem" }}>
              <input type="checkbox" checked={verifyTls} onChange={(e) => setVerifyTls(e.target.checked)} />
              Проверять TLS-сертификат сервера
            </label>
          </>
        )}

        {targetKind === "repository" && (
          <>
            <div className="field">
              <label>URL Git-репозитория</label>
              <input type="url" className="input" style={{ width: "100%" }} value={gitRepoUrl} onChange={(e) => setGitRepoUrl(e.target.value)} placeholder="https://github.com/org/mcp-server.git" />
            </div>
            <div className="field">
              <label>Токен доступа · только для приватных репозиториев по HTTPS</label>
              <input type="password" className="input" style={{ width: "100%" }} value={gitAccessToken} onChange={(e) => setGitAccessToken(e.target.value)} placeholder="ghp_... / glpat-..." autoComplete="off" />
            </div>
          </>
        )}

        {targetKind === "bundle" && (
          <>
            <div className="field">
              <label>Как получить MCPB</label>
              <select className="input" style={{ width: "100%" }} value={bundleSource} onChange={(e) => { setBundleSource(e.target.value as "upload" | "url"); setArtifact(null); }}>
                <option value="upload">Загрузить локальный файл</option>
                <option value="url">Скачать по HTTPS URI</option>
              </select>
            </div>
            {bundleSource === "upload" ? (
              <div className="field">
                <input type="file" accept=".mcpb,application/zip" onChange={(e) => { setBundleFile(e.target.files?.[0] ?? null); setArtifact(null); }} />
              </div>
            ) : (
              <>
                <div className="field">
                  <label>HTTPS URI архива</label>
                  <input type="url" className="input" style={{ width: "100%" }} value={bundleUrl} onChange={(e) => { setBundleUrl(e.target.value); setArtifact(null); }} placeholder="https://example.com/server.mcpb" />
                </div>
                <div className="field">
                  <label>Ожидаемый SHA-256</label>
                  <input className="input" style={{ width: "100%", fontFamily: "monospace" }} value={bundleExpectedSha} onChange={(e) => { setBundleExpectedSha(e.target.value); setArtifact(null); }} placeholder="Необязательно" />
                </div>
              </>
            )}
            <button type="button" className="btn btn-secondary" onClick={handleUploadBundle} disabled={artifactUploading}>
              {artifactUploading ? "Загрузка…" : "Загрузить и проверить MCPB"}
            </button>
            {artifactError && <p style={{ color: "var(--danger)", margin: "0.5rem 0 0" }}>{artifactError}</p>}
            {artifact && (
              <p style={{ margin: "0.5rem 0 0", color: "var(--success)" }}>
                Загружен {artifact.original_filename} ({Math.ceil(artifact.size_bytes / 1024)} КиБ), SHA-256: <code>{artifact.sha256}</code>
              </p>
            )}
          </>
        )}

        {error && (
          <p role="alert" style={{ color: "var(--danger)", fontSize: 13 }}>{error}</p>
        )}
        <div style={{ marginTop: "1.5rem" }}>
          {targetKind === "remote" && (
            <button className="btn" onClick={submit} disabled={busy || !sourceReady}>
              {busy ? "Сохранение…" : "Создать актив"}
            </button>
          )}
          {targetKind === "repository" && (
            <button className="btn" onClick={handleLoadRepo} disabled={loadingRepo || !gitRepoUrl.trim()}>
              {loadingRepo ? "Клонирование…" : "Загрузить репозиторий"}
            </button>
          )}
          {targetKind === "bundle" && (
            <div style={{ display: "flex", gap: "0.6rem" }}>
              <button className="btn" onClick={submit} disabled={busy || !sourceReady}>
                {busy ? "Сохранение…" : "Создать актив сразу"}
              </button>
              <button className="btn btn-secondary" onClick={() => { setError(null); setStep("deploy"); }} disabled={!sourceReady}>
                Настроить деплой
              </button>
            </div>
          )}
          {!name.trim() && (
            <p style={{ fontSize: 12, color: "var(--text-500)", margin: "0.6rem 0 0" }}>
              Название можно не указывать — сгенерируем из источника.
            </p>
          )}
        </div>
      </div>
    );
  }

  if (step === "repo") {
    return (
      <div className="card" style={{ marginBottom: "2.4rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ marginTop: 0 }}>Шаг 2. Репозиторий склонирован</h2>
          <button type="button" className="btn btn-secondary" onClick={() => setStep("source")}>
            ← К источнику
          </button>
        </div>
        <p style={{ fontSize: 13, color: "var(--text-500)", margin: "0 0 1.6rem" }}>
          Выберите ветку из доступных. Дальше можно создать актив сразу — или настроить деплой для динамического сканирования.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.6rem" }}>
          <div className="field">
            <label>Ветка</label>
            <select className="input" style={{ width: "100%" }} value={gitRef} onChange={(e) => handleBranchChange(e.target.value)} disabled={inspecting}>
              {branches.map((b) => (
                <option key={b} value={b}>{b}</option>
              ))}
            </select>
          </div>
        </div>

        {error && (
          <p role="alert" style={{ color: "var(--danger)", fontSize: 13 }}>{error}</p>
        )}
        <div style={{ display: "flex", gap: "0.6rem", marginTop: "1.5rem" }}>
          <button className="btn" onClick={submit} disabled={busy || inspecting}>
            {busy ? "Сохранение…" : "Создать актив сразу"}
          </button>
          <button className="btn btn-secondary" onClick={() => setStep("deploy")} disabled={inspecting}>
            Настроить деплой
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="card" style={{ marginBottom: "2.4rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ marginTop: 0 }}>Шаг 3. Деплой · необязательно</h2>
        <button type="button" className="btn btn-secondary" onClick={() => setStep("repo")}>
          ← Назад
        </button>
      </div>
      <p style={{ fontSize: 13, color: "var(--text-500)", margin: "0 0 1.6rem" }}>
        Как поднять MCP-сервер из репозитория для динамического сканирования.
        Необязательно: без этих настроек доступны статические проверки (SAST).
        Взаимодействие с сервером всегда по MCP-протоколу — выбирать режим не нужно.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.6rem" }}>
        {targetKind === "repository" && (
          <div className="field">
            <label>Dockerfile</label>
            {dockerfiles.length > 0 ? (
              <select className="input" style={{ width: "100%" }} value={deployDockerfile} onChange={(e) => setDeployDockerfile(e.target.value)} disabled={inspecting}>
                {dockerfiles.map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            ) : (
              <input className="input" style={{ width: "100%" }} value={deployDockerfile} onChange={(e) => setDeployDockerfile(e.target.value)} placeholder="Dockerfile" />
            )}
          </div>
        )}
        <div className="field">
          <label>Порт MCP-сервера</label>
          <input type="number" className="input" style={{ width: "100%" }} value={deployPort} onChange={(e) => setDeployPort(e.target.value)} placeholder="8000" />
        </div>
      </div>
      <div className="field">
        <label>URL path к MCP</label>
        <input className="input" style={{ width: "100%" }} value={deployMcpPath} onChange={(e) => setDeployMcpPath(e.target.value)} placeholder="/mcp" />
      </div>

      {targetKind === "bundle" && (
        <div className="field">
          <label>Пользовательская конфигурация MCPB</label>
          <textarea className="input" style={{ width: "100%", resize: "vertical", fontFamily: "monospace" }} rows={3} value={bundleUserConfig} onChange={(e) => setBundleUserConfig(e.target.value)} placeholder="{}" />
        </div>
      )}

      <div className="field">
        <label>Переменные окружения сервера · имя + значение</label>
        {deployEnvRows.map((row, i) => (
          <div key={i} style={{ display: "flex", gap: 8, marginBottom: 8 }}>
            <input placeholder="MCP_TOKEN" value={row.key} onChange={(e) => updateDeployEnvRow(i, "key", e.target.value)} />
            <input placeholder="значение" value={row.value} onChange={(e) => updateDeployEnvRow(i, "value", e.target.value)} />
          </div>
        ))}
        <button type="button" className="btn btn-secondary" onClick={() => setDeployEnvRows((r) => [...r, { key: "", value: "" }])}>
          + Добавить переменную
        </button>
      </div>

      {error && (
        <p role="alert" style={{ color: "var(--danger)", fontSize: 13 }}>{error}</p>
      )}
      <button className="btn" onClick={submit} disabled={busy || inspecting}>
        {busy ? "Сохранение…" : "Создать актив"}
      </button>
    </div>
  );
}

function SkillsAssetsTab() {
  const [assets, setAssets] = useState<SkillAsset[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<SkillAsset | null>(null);

  const load = () => api.get<SkillAsset[]>("/skill-assets").then(setAssets).catch((e) => setError(String(e)));
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleDelete = async (id: number) => {
    setError(null);
    try {
      await api.delete(`/skill-assets/${id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div>
      <div className="section-heading">
        <h2 style={{ margin: 0 }}>Skill-активы</h2>
        <button className="btn btn-primary" onClick={() => {setEditing(null); setShowForm(!showForm);}}>
          {showForm ? "Отмена" : "+ Добавить Skills"}
        </button>
      </div>
      {error && (
        <div className="card" style={{ padding: "1rem 1.5rem", marginBottom: "1rem", borderLeft: "0.3rem solid var(--danger)" }}>
          <span style={{ color: "var(--danger)" }}>{error}</span>
        </div>
      )}
      {showForm && (
        <SkillAssetForm
          key={editing?.id ?? "new"}
          asset={editing ?? undefined}
          onClose={() => {setShowForm(false); setEditing(null);}}
          onCreated={() => {
            setShowForm(false);
            setEditing(null);
            load();
          }}
        />
      )}
      <div className="card data-table-card">
        {assets.length === 0 ? (
          <div style={{ padding: "3.2rem", textAlign: "center" }}>
            <p style={{ margin: 0, color: "var(--text-700)", fontWeight: 500 }}>Пока нет ни одного skill-актива</p>
            <p style={{ margin: "0.6rem 0 0", color: "var(--text-500)", fontSize: 13 }}>
              Добавьте набор skills из репозитория или zip-архива. Сканирование skills появится позже.
            </p>
          </div>
        ) : (
          <table className="data-table data-table--assets" aria-label="Skill-активы">
            <colgroup><col /><col /><col /><col /></colgroup>
            <thead>
              <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                <th scope="col">Название</th><th scope="col">Источник</th><th scope="col">Создан</th><th scope="col">Действия</th>
              </tr>
            </thead>
            <tbody>
              {assets.map((asset) => (
                <tr key={asset.id} style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                  <td data-label="Название"><div className="table-name">
                    <Link className="table-name-link" to={`/assets/skill/${asset.id}`}>
                      {asset.name}
                    </Link>
                    <span className="asset-labels"><span className="badge badge-neutral">есть код</span></span>
                    {asset.description && (
                      <div style={{ color: "var(--text-500)", fontSize: 12, marginTop: "0.3rem" }}>{asset.description}</div>
                    )}
                  </div></td>
                  <td data-label="Источник">
                    {asset.source === "zip" ? "ZIP-архив" : "Git-репозиторий"}
                  </td>
                  <td data-label="Создан">{new Date(asset.created_at).toLocaleString("ru-RU")}</td>
                  <td data-label="Действия">
                    <AssetActions onEdit={() => {setEditing(asset); setShowForm(true); setError(null);}} onDelete={() => handleDelete(asset.id)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function SkillAssetForm({ asset, onClose, onCreated }: { asset?: SkillAsset; onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState(asset?.name ?? "");
  const [description, setDescription] = useState(asset?.description ?? "");
  const [source, setSource] = useState<"repository" | "zip">(asset?.source ?? "repository");
  const [gitRepoUrl, setGitRepoUrl] = useState(asset?.git_repo_url ?? "");
  const [gitRef, setGitRef] = useState(asset?.git_ref ?? "main");
  const [gitAccessToken, setGitAccessToken] = useState("");
  const [clearToken, setClearToken] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canCreate = Boolean(name.trim()) && (source === "repository" ? Boolean(gitRepoUrl.trim()) : Boolean(asset || file));

  const submit = async () => {
    if (!canCreate) return;
    setBusy(true);
    setError(null);
    try {
      if (asset) {
        await api.put(`/skill-assets/${asset.id}`, {
          name: name.trim(), description: description.trim() || null,
          ...(source === "repository" && {git_repo_url: gitRepoUrl.trim(), git_ref: gitRef.trim() || "main",
            ...(clearToken ? {git_access_token: null} : gitAccessToken ? {git_access_token: gitAccessToken} : {})}),
        });
      } else if (source === "repository") {
        await api.post<SkillAsset>("/skill-assets", {
          name: name.trim(),
          description: description.trim() || null,
          git_repo_url: gitRepoUrl.trim(),
          git_ref: gitRef.trim() || "main",
          git_access_token: gitAccessToken.trim() || null,
        });
      } else {
        if (!file) throw new Error("Выберите zip-архив");
        const formData = new FormData();
        formData.append("name", name.trim());
        formData.append("description", description.trim());
        formData.append("file", file);
        await api.postForm<SkillAsset>("/skill-assets/upload", formData);
      }
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="card asset-edit-form"
      aria-label={asset ? "Редактирование skill-актива" : "Новый skill-актив"}
      style={{ padding: "2rem", minWidth: 0 }}
      onSubmit={(e) => { e.preventDefault(); void submit(); }}
    >
        <h2 style={{ marginBottom: "1rem" }}>{asset ? "Изменить skill-актив" : "Новый skill-актив"}</h2>
        <div style={{ marginBottom: "1rem" }}>
          <label style={{ display: "block", marginBottom: "0.5rem" }}>
            Название<span style={{ color: "var(--danger)" }}> *</span>
          </label>
          <input aria-label="Название" className="input" style={{ width: "100%" }} value={name} onChange={(e) => setName(e.target.value)} placeholder="Например: навыки поддержки" />
        </div>
        <div style={{ marginBottom: "1rem" }}>
          <label style={{ display: "block", marginBottom: "0.5rem" }}>Описание</label>
          <input aria-label="Описание" className="input" style={{ width: "100%" }} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Необязательно" />
        </div>
        <div style={{ marginBottom: "1rem" }}>
          <label style={{ display: "block", marginBottom: "0.5rem" }}>Источник</label>
          <select aria-label="Источник" className="input" style={{ width: "100%" }} value={source} disabled={Boolean(asset)} onChange={(e) => setSource(e.target.value as "repository" | "zip")}>
            <option value="repository">Git-репозиторий</option>
            <option value="zip">ZIP-архив</option>
          </select>
        </div>

        {source === "repository" ? (
          <>
            <div style={{ marginBottom: "1rem" }}>
              <label style={{ display: "block", marginBottom: "0.5rem" }}>URL Git-репозитория</label>
              <input aria-label="URL Git-репозитория" type="url" className="input" style={{ width: "100%" }} value={gitRepoUrl} onChange={(e) => setGitRepoUrl(e.target.value)} placeholder="https://github.com/org/skills.git" />
            </div>
            <div style={{ marginBottom: "1rem" }}>
              <label style={{ display: "block", marginBottom: "0.5rem" }}>Ветка, тег или commit</label>
              <input aria-label="Ветка, тег или commit" className="input" style={{ width: "100%" }} value={gitRef} onChange={(e) => setGitRef(e.target.value)} />
            </div>
            <div style={{ marginBottom: "1rem" }}>
              <label style={{ display: "block", marginBottom: "0.5rem" }}>Токен доступа к Git</label>
              <input aria-label="Токен доступа к Git" type="password" className="input" style={{ width: "100%" }} value={gitAccessToken} onChange={(e) => setGitAccessToken(e.target.value)} placeholder={asset ? "Пусто — сохранить прежний токен" : "Необязательно, для приватного репозитория"} disabled={clearToken} autoComplete="off" />
              {asset && <label className="checkbox-setting"><input type="checkbox" checked={clearToken} onChange={e => setClearToken(e.target.checked)} />Удалить сохранённый токен</label>}
            </div>
          </>
        ) : (
          <div style={{ marginBottom: "1rem" }}>
            <label style={{ display: "block", marginBottom: "0.5rem" }}>ZIP-архив</label>
            {asset ? <p>{asset.archive_filename} · архив сохраняется при редактировании имени и описания.</p> : <input type="file" accept=".zip,application/zip" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />}
          </div>
        )}

        {error && (
          <p role="alert" style={{ color: "var(--danger)", fontSize: 13 }}>{error}</p>
        )}
        <div className="asset-form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>Отмена</button>
          <button type="submit" className="btn btn-primary" disabled={busy || !canCreate}>
            {busy ? "Сохранение…" : asset ? "Сохранить изменения" : "Создать актив"}
          </button>
        </div>
    </form>
  );
}
