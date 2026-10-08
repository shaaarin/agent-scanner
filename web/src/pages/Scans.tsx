import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type {
  Scan, ScanType, AgentConfig, LLMModel, CodeScanSeverity, MCPArtifact, MCPTransport, MCPTargetKind,
} from "../api/types";
import { SEVERITY_LABELS, SEVERITY_ORDER, scanTypeLabel } from "../api/scanTypes";
import { PageHeader } from "../components/PageHeader";

const DEEPTEAM_VULNERABILITIES = [
  "BFLA", "BOLA", "RBAC", "DebugAccess", "ShellInjection", 
  "SQLInjection", "SSRF", "ToolMetadataPoisoning", "CrossContextRetrieval", 
  "SystemReconnaissance", "GoalTheft", "RecursiveHijacking", 
  "ExcessiveAgency", "Robustness", "IndirectInstruction", 
  "ToolOrchestrationAbuse", "AgentIdentityTrustAbuse", 
  "InterAgentCommunicationCompromise", "AutonomousAgentDrift", 
  "ExploitToolAgent", "ExternalSystemAbuse"
];

const DEEPTEAM_ATTACKS = [
  "PromptInjection", "Roleplay", "Leetspeak", "ROT13", "Base64", 
  "GrayBox", "MathProblem", "Multilingual", "PromptProbing", 
  "AdversarialPoetry", "SystemOverride", "PermissionEscalation", 
  "GoalRedirection", "LinguisticConfusion", "InputBypass", 
  "ContextPoisoning", "CharacterStream", "ContextFlooding", 
  "EmbeddedInstructionJSON", "SyntheticContextInjection", 
  "AuthorityEscalation", "EmotionalManipulation"
];

// Идентификаторы должны совпадать с реестром scanner-mcp. Пока реализации
// сканеров не подключены, список пуст; scanner_ids: [] означает «запустить
// все доступные проверки».
const MCP_SCANNERS: string[] = [];

export function Scans() {
  const navigate = useNavigate();
  const [scans, setScans] = useState<Scan[]>([]);
  const [agentConfigs, setAgentConfigs] = useState<AgentConfig[]>([]);
  const [llmModels, setLlmModels] = useState<LLMModel[]>([]);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newScanName, setNewScanName] = useState("");
  const [newScanType, setNewScanType] = useState<ScanType>("deep_team");
  const [selectedAgentId, setSelectedAgentId] = useState<number | null>(null);
  const [selectedLlmModelId, setSelectedLlmModelId] = useState<number | null>(null);
  const [selectedVulnerabilities, setSelectedVulnerabilities] = useState<string[]>([]);
  const [selectedAttacks, setSelectedAttacks] = useState<string[]>([]);
  const [minSeverity, setMinSeverity] = useState<CodeScanSeverity>("medium");
  const [guidance, setGuidance] = useState("");
  const [mcpTargetKind, setMcpTargetKind] = useState<MCPTargetKind>("remote");
  const [mcpServerUrl, setMcpServerUrl] = useState("");
  const [mcpTransport, setMcpTransport] = useState<MCPTransport>("auto");
  const [mcpBearerToken, setMcpBearerToken] = useState("");
  const [mcpHeaders, setMcpHeaders] = useState("{}");
  const [selectedMcpScanners, setSelectedMcpScanners] = useState<string[]>([]);
  const [mcpTimeoutSeconds, setMcpTimeoutSeconds] = useState(30);
  const [mcpVerifyTls, setMcpVerifyTls] = useState(true);
  const [mcpGitRepoUrl, setMcpGitRepoUrl] = useState("");
  const [mcpGitRef, setMcpGitRef] = useState("main");
  const [mcpGitAccessToken, setMcpGitAccessToken] = useState("");
  const [mcpConfigPath, setMcpConfigPath] = useState("mcp_config.json");
  const [mcpRepoEnv, setMcpRepoEnv] = useState("{}");
  const [mcpBundleSource, setMcpBundleSource] = useState<"upload" | "url">("upload");
  const [mcpBundleFile, setMcpBundleFile] = useState<File | null>(null);
  const [mcpBundleUrl, setMcpBundleUrl] = useState("");
  const [mcpBundleExpectedSha, setMcpBundleExpectedSha] = useState("");
  const [mcpBundleUserConfig, setMcpBundleUserConfig] = useState("{}");
  const [mcpArtifact, setMcpArtifact] = useState<MCPArtifact | null>(null);
  const [mcpArtifactUploading, setMcpArtifactUploading] = useState(false);
  const [mcpArtifactError, setMcpArtifactError] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);

  // Модель-судья нужна только динамическому тестированию (DeepTeam).
  const needsLlmModel = newScanType === "deep_team";
  const needsAgent = newScanType !== "mcp";
  const hasMcpTarget = mcpTargetKind === "remote"
    ? Boolean(mcpServerUrl.trim())
    : mcpTargetKind === "repository"
      ? Boolean(mcpGitRepoUrl.trim() && mcpGitRef.trim() && mcpConfigPath.trim())
      : Boolean(mcpArtifact);
  const hasRequiredTarget = newScanType === "mcp" ? hasMcpTarget : Boolean(selectedAgentId);
  const canCreate = Boolean(newScanName.trim() && hasRequiredTarget && (!needsLlmModel || selectedLlmModelId));

  useEffect(() => {
    Promise.all([
      api.get<Scan[]>("/scans").then(setScans),
      api.get<AgentConfig[]>("/agent-configs").then(setAgentConfigs),
      api.get<LLMModel[]>("/llm-models").then(setLlmModels),
    ]);
  }, []);

  useEffect(() => {
    if (!scans.some((scan) => scan.status === "running")) return;
    const timer = setInterval(() => {
      api.get<Scan[]>("/scans").then(setScans);
    }, 2000);
    return () => clearInterval(timer);
  }, [scans]);

  const parseStringMap = (value: string, label: string): Record<string, string> => {
    const parsed: unknown = JSON.parse(value || "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error(`${label} должны быть JSON-объектом`);
    }
    return Object.fromEntries(Object.entries(parsed).map(([name, item]) => {
      if (typeof item !== "string") throw new Error(`Значение ${name} должно быть строкой`);
      return [name, item];
    }));
  };

  const handleUploadMcpBundle = async () => {
    setMcpArtifactError(null);
    setMcpArtifactUploading(true);
    try {
      let artifact: MCPArtifact;
      if (mcpBundleSource === "upload") {
        if (!mcpBundleFile) throw new Error("Выберите MCPB-файл");
        const formData = new FormData();
        formData.append("file", mcpBundleFile);
        artifact = await api.postForm<MCPArtifact>("/mcp-artifacts/upload", formData);
      } else {
        if (!mcpBundleUrl.trim()) throw new Error("Укажите HTTPS URI MCPB-архива");
        artifact = await api.post<MCPArtifact>("/mcp-artifacts/from-url", {
          url: mcpBundleUrl.trim(),
          expected_sha256: mcpBundleExpectedSha.trim() || null,
        });
      }
      setMcpArtifact(artifact);
    } catch (error) {
      setMcpArtifact(null);
      setMcpArtifactError(error instanceof Error ? error.message : String(error));
    } finally {
      setMcpArtifactUploading(false);
    }
  };

  const handleCreateScan = async () => {
    if (!canCreate) return;

    setCreateError(null);
    try {
      const config: Record<string, unknown> = {};

      if (newScanType === "deep_team") {
        config.eval_llm_model_id = selectedLlmModelId;
        config.vulnerabilities = selectedVulnerabilities.length > 0 ? selectedVulnerabilities : ["BFLA", "BOLA", "RBAC"];
        config.attacks = selectedAttacks.length > 0 ? selectedAttacks : ["PromptInjection"];
      } else if (newScanType === "code_scan") {
        config.min_severity = minSeverity;
        config.guidance = guidance.trim() || null;
      } else if (newScanType === "mcp") {
        if (mcpTargetKind === "remote") {
          const headers = parseStringMap(mcpHeaders, "Дополнительные заголовки");
          if (mcpBearerToken.trim()) headers.Authorization = `Bearer ${mcpBearerToken.trim()}`;
          config.target = {
            kind: "remote", server_url: mcpServerUrl.trim(), transport: mcpTransport, headers, verify_tls: mcpVerifyTls,
          };
        } else if (mcpTargetKind === "repository") {
          config.target = {
            kind: "repository",
            git_repo_url: mcpGitRepoUrl.trim(),
            git_ref: mcpGitRef.trim(),
            git_access_token: mcpGitAccessToken.trim() || null,
            config_path: mcpConfigPath.trim(),
            env: parseStringMap(mcpRepoEnv, "Переменные окружения"),
          };
        } else {
          if (!mcpArtifact) throw new Error("Сначала загрузите MCPB-архив");
          const userConfig: unknown = JSON.parse(mcpBundleUserConfig || "{}");
          if (!userConfig || typeof userConfig !== "object" || Array.isArray(userConfig)) {
            throw new Error("Пользовательская конфигурация MCPB должна быть JSON-объектом");
          }
          config.target = { kind: "bundle", artifact_id: mcpArtifact.id, user_config: userConfig };
        }
        config.scanner_ids = selectedMcpScanners;
        config.timeout_seconds = mcpTimeoutSeconds;
      }

      await api.post("/scans", {
        name: newScanName.trim(),
        type: newScanType,
        agent_config_id: needsAgent ? selectedAgentId : null,
        status: "pending",
        session_id: `scan-${Date.now()}`,
        config: JSON.stringify(config),
      });
      setShowCreateModal(false);
      setNewScanName("");
      setSelectedAgentId(null);
      setSelectedLlmModelId(null);
      setSelectedVulnerabilities([]);
      setSelectedAttacks([]);
      setMinSeverity("medium");
      setGuidance("");
      setMcpTargetKind("remote");
      setMcpServerUrl("");
      setMcpTransport("auto");
      setMcpBearerToken("");
      setMcpHeaders("{}");
      setSelectedMcpScanners([]);
      setMcpTimeoutSeconds(30);
      setMcpVerifyTls(true);
      setMcpGitRepoUrl("");
      setMcpGitRef("main");
      setMcpGitAccessToken("");
      setMcpConfigPath("mcp_config.json");
      setMcpRepoEnv("{}");
      setMcpBundleSource("upload");
      setMcpBundleFile(null);
      setMcpBundleUrl("");
      setMcpBundleExpectedSha("");
      setMcpBundleUserConfig("{}");
      setMcpArtifact(null);
      setMcpArtifactError(null);
      api.get<Scan[]>("/scans").then(setScans);
    } catch (error) {
      console.error("Failed to create scan:", error);
      setCreateError(error instanceof Error ? error.message : String(error));
    }
  };

  const handleStartScan = async (scanId: number) => {
    setPageError(null);
    try {
      await api.post(`/scans/${scanId}/start`, {});
      navigate(`/scans/${scanId}`);
    } catch (error) {
      console.error("Failed to start scan:", error);
      setPageError(`Не удалось запустить сканирование: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const handleDeleteScan = async (scanId: number) => {
    setPageError(null);
    try {
      await api.delete(`/scans/${scanId}`);
      api.get<Scan[]>("/scans").then(setScans);
    } catch (error) {
      console.error("Failed to delete scan:", error);
      setPageError(`Не удалось удалить сканирование: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const getStatusBadge = (status: string) => {
    const colors: Record<string, string> = {
      pending: "badge-secondary",
      running: "badge-primary",
      completed: "badge-success",
      failed: "badge-danger",
    };
    const labels: Record<string, string> = {
      pending: "Ожидает запуска",
      running: "Выполняется",
      completed: "Завершено",
      failed: "Ошибка",
    };
    return <span className={`badge ${colors[status] || "badge-secondary"}`}>{labels[status] || status}</span>;
  };

  return (
    <div>
      <PageHeader
        title="Сканирования"
        description="Проверка безопасности агентов: динамическое тестирование, анализ кода, MCP и Agent Skills."
        actions={
          <button
            className="btn btn-primary"
            onClick={() => setShowCreateModal(true)}
          >
            + Новое сканирование
          </button>
        }
      />

      {pageError && (
        <div className="card" style={{ padding: "1rem 1.5rem", marginBottom: "1rem", borderLeft: "0.3rem solid var(--danger)" }}>
          <span style={{ color: "var(--danger)" }}>{pageError}</span>
        </div>
      )}

      <div className="card">
        {scans.length === 0 ? (
          <div style={{ padding: "3.2rem", textAlign: "center" }}>
            <p style={{ margin: 0, color: "var(--text-700)", fontWeight: 500 }}>
              Здесь появятся ваши сканирования
            </p>
            <p style={{ margin: "0.6rem 0 0", color: "var(--text-500)", fontSize: 13 }}>
              Создайте первое сканирование, чтобы проверить агента на устойчивость к атакам.
            </p>
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                <th style={{ padding: "1rem", textAlign: "left" }}>Название</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Тип</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Статус</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Создано</th>
                <th style={{ padding: "1rem", textAlign: "right" }}>Действия</th>
              </tr>
            </thead>
            <tbody>
              {scans.map((scan) => (
                <tr key={scan.id} style={{ borderBottom: "0.1rem solid var(--separator-default)" }}>
                  <td style={{ padding: "1rem" }}>
                    <button
                      className="btn btn-sm btn-secondary"
                      onClick={() => navigate(`/scans/${scan.id}`)}
                    >
                      {scan.name}
                    </button>
                  </td>
                  <td style={{ padding: "1rem" }}>{scanTypeLabel(scan.type)}</td>
                  <td style={{ padding: "1rem" }}>{getStatusBadge(scan.status)}</td>
                  <td style={{ padding: "1rem" }}>
                    {new Date(scan.created_at).toLocaleString("ru-RU")}
                  </td>
                  <td style={{ padding: "1rem", textAlign: "right" }}>
                    {scan.status === "pending" && (
                      <button
                        className="btn btn-sm btn-primary"
                        onClick={() => handleStartScan(scan.id)}
                        style={{ marginRight: "0.5rem" }}
                      >
                        Запустить
                      </button>
                    )}
                    <button
                      className="btn btn-sm btn-danger"
                      onClick={() => handleDeleteScan(scan.id)}
                    >
                      Удалить
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showCreateModal && (
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
          onClick={() => setShowCreateModal(false)}
        >
          <div
            className="card"
            style={{ padding: "2rem", minWidth: "500px", maxWidth: "700px", maxHeight: "90vh", overflow: "auto" }}
            onClick={(e) => e.stopPropagation()}
          >
            <h2 style={{ marginBottom: "0.6rem" }}>Новое сканирование</h2>
            <p style={{ margin: "0 0 1.5rem", color: "var(--text-500)", fontSize: 13 }}>
              {newScanType === "code_scan"
                ? "Платформа скачает код агента из его репозитория и проверит его через promptfoo. Агент не запускается, анализ выполняется в облаке Promptfoo."
                : newScanType === "mcp"
                ? "Платформа подключится к удалённому MCP-серверу и запустит выбранные проверки безопасности."
                : "Платформа запустит агента и проверит его ответы на выбранные классы атак."}
            </p>
            <div style={{ marginBottom: "1rem" }}>
              <label style={{ display: "block", marginBottom: "0.5rem" }}>Название сканирования</label>
              <input
                type="text"
                className="input"
                value={newScanName}
                onChange={(e) => setNewScanName(e.target.value)}
                placeholder="Например: проверка агента поддержки"
                style={{ width: "100%" }}
              />
            </div>
            <div style={{ marginBottom: "1rem" }}>
              <label style={{ display: "block", marginBottom: "0.5rem" }}>Тип сканирования</label>
              <select
                className="input"
                value={newScanType}
                onChange={(e) => setNewScanType(e.target.value as ScanType)}
                style={{ width: "100%" }}
              >
                <option value="deep_team">Динамическое тестирование</option>
                <option value="code_scan">Анализ кода (promptfoo)</option>
                <option value="mcp">MCP (в разработке)</option>
                <option value="agent_skills">Agent Skills (в разработке)</option>
              </select>
            </div>
            {needsAgent && (
            <div style={{ marginBottom: "1rem" }}>
              <label style={{ display: "block", marginBottom: "0.5rem" }}>Тестируемый агент</label>
              <select
                className="input"
                value={selectedAgentId || ""}
                onChange={(e) => setSelectedAgentId(Number(e.target.value))}
                style={{ width: "100%" }}
              >
                <option value="">Выберите агента</option>
                {agentConfigs.map((config) => (
                  <option key={config.id} value={config.id}>
                    {config.name}
                  </option>
                ))}
              </select>
            </div>
            )}
            {needsLlmModel && (
            <div style={{ marginBottom: "1rem" }}>
              <label style={{ display: "block", marginBottom: "0.5rem" }}>LLM-модель для оценки</label>
              <select
                className="input"
                value={selectedLlmModelId || ""}
                onChange={(e) => setSelectedLlmModelId(Number(e.target.value))}
                style={{ width: "100%" }}
              >
                <option value="">Выберите модель</option>
                {llmModels.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name} ({model.provider_type} - {model.model})
                  </option>
                ))}
              </select>
              <p style={{ margin: "0.4rem 0 0", fontSize: 12, color: "var(--text-500)" }}>
                Ею будут генерироваться атаки и оцениваться ответы агента.
              </p>
            </div>
            )}

            {newScanType === "mcp" && (
              <>
                <div style={{ marginBottom: "1rem" }}>
                  <label style={{ display: "block", marginBottom: "0.5rem" }}>Источник MCP-сервера</label>
                  <select
                    className="input"
                    value={mcpTargetKind}
                    onChange={(e) => setMcpTargetKind(e.target.value as MCPTargetKind)}
                    style={{ width: "100%" }}
                  >
                    <option value="remote">Удалённый сервер</option>
                    <option value="repository">Git-репозиторий</option>
                    <option value="bundle">MCPB-архив</option>
                  </select>
                </div>

                {mcpTargetKind === "remote" && <>
                  <div style={{ marginBottom: "1rem" }}>
                    <label style={{ display: "block", marginBottom: "0.5rem" }}>Адрес MCP-сервера</label>
                    <input type="url" className="input" value={mcpServerUrl} onChange={(e) => setMcpServerUrl(e.target.value)} placeholder="https://example.com/mcp" style={{ width: "100%" }} />
                  </div>
                  <div style={{ marginBottom: "1rem" }}>
                    <label style={{ display: "block", marginBottom: "0.5rem" }}>Транспорт MCP</label>
                    <select className="input" value={mcpTransport} onChange={(e) => setMcpTransport(e.target.value as MCPTransport)} style={{ width: "100%" }}>
                      <option value="auto">Автоопределение</option>
                      <option value="streamable_http">Streamable HTTP</option>
                      <option value="sse">Legacy SSE</option>
                    </select>
                  </div>
                  <div style={{ marginBottom: "1rem" }}>
                    <label style={{ display: "block", marginBottom: "0.5rem" }}>Bearer Token</label>
                    <input type="password" className="input" value={mcpBearerToken} onChange={(e) => setMcpBearerToken(e.target.value)} placeholder="Необязательно" autoComplete="off" style={{ width: "100%" }} />
                  </div>
                  <div style={{ marginBottom: "1rem" }}>
                    <label style={{ display: "block", marginBottom: "0.5rem" }}>Дополнительные заголовки</label>
                    <textarea className="input" value={mcpHeaders} onChange={(e) => setMcpHeaders(e.target.value)} placeholder={'{"X-API-Key": "value"}'} rows={3} style={{ width: "100%", resize: "vertical", fontFamily: "monospace" }} />
                    <p style={{ margin: "0.4rem 0 0", fontSize: 12, color: "var(--text-500)" }}>JSON-объект со строковыми значениями. Bearer Token будет добавлен как Authorization.</p>
                  </div>
                  <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "1rem" }}>
                    <input type="checkbox" checked={mcpVerifyTls} onChange={(e) => setMcpVerifyTls(e.target.checked)} />
                    Проверять TLS-сертификат сервера
                  </label>
                </>}

                {mcpTargetKind === "repository" && <>
                  <div style={{ marginBottom: "1rem" }}>
                    <label style={{ display: "block", marginBottom: "0.5rem" }}>URL Git-репозитория</label>
                    <input type="url" className="input" value={mcpGitRepoUrl} onChange={(e) => setMcpGitRepoUrl(e.target.value)} placeholder="https://github.com/org/mcp-server.git" style={{ width: "100%" }} />
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1rem" }}>
                    <div><label style={{ display: "block", marginBottom: "0.5rem" }}>Ветка, тег или commit</label><input className="input" value={mcpGitRef} onChange={(e) => setMcpGitRef(e.target.value)} style={{ width: "100%" }} /></div>
                    <div><label style={{ display: "block", marginBottom: "0.5rem" }}>Путь к конфигурации</label><input className="input" value={mcpConfigPath} onChange={(e) => setMcpConfigPath(e.target.value)} placeholder="mcp_config.json" style={{ width: "100%" }} /></div>
                  </div>
                  <div style={{ marginBottom: "1rem" }}>
                    <label style={{ display: "block", marginBottom: "0.5rem" }}>Токен доступа к Git</label>
                    <input type="password" className="input" value={mcpGitAccessToken} onChange={(e) => setMcpGitAccessToken(e.target.value)} placeholder="Необязательно, для приватного репозитория" autoComplete="off" style={{ width: "100%" }} />
                  </div>
                  <div style={{ marginBottom: "1rem" }}>
                    <label style={{ display: "block", marginBottom: "0.5rem" }}>Переменные окружения</label>
                    <textarea className="input" value={mcpRepoEnv} onChange={(e) => setMcpRepoEnv(e.target.value)} placeholder={'{"API_KEY": "value"}'} rows={3} style={{ width: "100%", resize: "vertical", fontFamily: "monospace" }} />
                  </div>
                </>}

                {mcpTargetKind === "bundle" && <>
                  <div style={{ marginBottom: "1rem" }}>
                    <label style={{ display: "block", marginBottom: "0.5rem" }}>Как получить MCPB</label>
                    <select className="input" value={mcpBundleSource} onChange={(e) => { setMcpBundleSource(e.target.value as "upload" | "url"); setMcpArtifact(null); }} style={{ width: "100%" }}>
                      <option value="upload">Загрузить локальный файл</option>
                      <option value="url">Скачать по HTTPS URI</option>
                    </select>
                  </div>
                  {mcpBundleSource === "upload" ? (
                    <div style={{ marginBottom: "1rem" }}><input type="file" accept=".mcpb,application/zip" onChange={(e) => { setMcpBundleFile(e.target.files?.[0] ?? null); setMcpArtifact(null); }} /></div>
                  ) : <>
                    <div style={{ marginBottom: "1rem" }}><label style={{ display: "block", marginBottom: "0.5rem" }}>HTTPS URI архива</label><input type="url" className="input" value={mcpBundleUrl} onChange={(e) => { setMcpBundleUrl(e.target.value); setMcpArtifact(null); }} placeholder="https://example.com/server.mcpb" style={{ width: "100%" }} /></div>
                    <div style={{ marginBottom: "1rem" }}><label style={{ display: "block", marginBottom: "0.5rem" }}>Ожидаемый SHA-256</label><input className="input" value={mcpBundleExpectedSha} onChange={(e) => { setMcpBundleExpectedSha(e.target.value); setMcpArtifact(null); }} placeholder="Необязательно" style={{ width: "100%", fontFamily: "monospace" }} /></div>
                  </>}
                  <button type="button" className="btn btn-secondary" onClick={handleUploadMcpBundle} disabled={mcpArtifactUploading} style={{ marginBottom: "1rem" }}>
                    {mcpArtifactUploading ? "Загрузка…" : "Загрузить и проверить MCPB"}
                  </button>
                  {mcpArtifactError && <p style={{ color: "var(--danger)", margin: "0 0 1rem" }}>{mcpArtifactError}</p>}
                  {mcpArtifact && <p style={{ margin: "0 0 1rem", color: "var(--success)" }}>Загружен {mcpArtifact.original_filename} ({Math.ceil(mcpArtifact.size_bytes / 1024)} КиБ), SHA-256: <code>{mcpArtifact.sha256}</code></p>}
                  <div style={{ marginBottom: "1rem" }}>
                    <label style={{ display: "block", marginBottom: "0.5rem" }}>Пользовательская конфигурация MCPB</label>
                    <textarea className="input" value={mcpBundleUserConfig} onChange={(e) => setMcpBundleUserConfig(e.target.value)} placeholder="{}" rows={3} style={{ width: "100%", resize: "vertical", fontFamily: "monospace" }} />
                  </div>
                </>}
                <div style={{ marginBottom: "1rem" }}>
                  <label style={{ display: "block", marginBottom: "0.5rem" }}>
                    MCP-сканеры · выбрано: {selectedMcpScanners.length}
                  </label>
                  <div style={{
                    maxHeight: "150px",
                    overflow: "auto",
                    border: "0.1rem solid var(--separator-default)",
                    borderRadius: "var(--radius-m)",
                    padding: "0.5rem",
                  }}>
                    {MCP_SCANNERS.length === 0 ? (
                      <p style={{ margin: 0, fontSize: "0.9rem", color: "var(--text-500)" }}>
                        Доступные MCP-сканеры пока не зарегистрированы. При пустом списке будут запущены все доступные проверки.
                      </p>
                    ) : (
                      MCP_SCANNERS.map((scannerId) => (
                        <label key={scannerId} style={{ display: "block", marginBottom: "0.25rem", fontSize: "0.9rem" }}>
                          <input
                            type="checkbox"
                            checked={selectedMcpScanners.includes(scannerId)}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setSelectedMcpScanners([...selectedMcpScanners, scannerId]);
                              } else {
                                setSelectedMcpScanners(selectedMcpScanners.filter((id) => id !== scannerId));
                              }
                            }}
                            style={{ marginRight: "0.5rem" }}
                          />
                          {scannerId}
                        </label>
                      ))
                    )}
                  </div>
                </div>
                <div style={{ marginBottom: "1rem" }}>
                  <label style={{ display: "block", marginBottom: "0.5rem" }}>Таймаут соединения, секунд</label>
                  <input
                    type="number"
                    className="input"
                    min={1}
                    max={300}
                    value={mcpTimeoutSeconds}
                    onChange={(e) => setMcpTimeoutSeconds(Number(e.target.value))}
                    style={{ width: "100%" }}
                  />
                </div>
              </>
            )}

            {newScanType === "code_scan" && (
              <>
                <div style={{ marginBottom: "1rem" }}>
                  <label style={{ display: "block", marginBottom: "0.5rem" }}>Минимальная серьёзность</label>
                  <select
                    className="input"
                    value={minSeverity}
                    onChange={(e) => setMinSeverity(e.target.value as CodeScanSeverity)}
                    style={{ width: "100%" }}
                  >
                    {SEVERITY_ORDER.slice().reverse().map((severity) => (
                      <option key={severity} value={severity}>
                        {SEVERITY_LABELS[severity]}
                      </option>
                    ))}
                  </select>
                  <p style={{ margin: "0.4rem 0 0", fontSize: 12, color: "var(--text-500)" }}>
                    Проблемы ниже этого уровня в отчёт не попадут.
                  </p>
                </div>
                <div style={{ marginBottom: "1.5rem" }}>
                  <label style={{ display: "block", marginBottom: "0.5rem" }}>Дополнительные инструкции сканеру</label>
                  <textarea
                    className="input"
                    value={guidance}
                    onChange={(e) => setGuidance(e.target.value)}
                    placeholder="Необязательно. Например: основной риск — инструменты работы с базой данных"
                    rows={3}
                    maxLength={4000}
                    style={{ width: "100%", resize: "vertical" }}
                  />
                </div>
              </>
            )}

            {newScanType === "deep_team" && (
              <>
                <div style={{ marginBottom: "1rem" }}>
                  <label style={{ display: "block", marginBottom: "0.5rem" }}>
                    Уязвимости · выбрано: {selectedVulnerabilities.length}
                  </label>
                  <div style={{ 
                    maxHeight: "150px", 
                    overflow: "auto", 
                    border: "0.1rem solid var(--separator-default)", 
                    borderRadius: "var(--radius-m)",
                    padding: "0.5rem"
                  }}>
                    {DEEPTEAM_VULNERABILITIES.map((vuln) => (
                      <label key={vuln} style={{ display: "block", marginBottom: "0.25rem", fontSize: "0.9rem" }}>
                        <input
                          type="checkbox"
                          checked={selectedVulnerabilities.includes(vuln)}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setSelectedVulnerabilities([...selectedVulnerabilities, vuln]);
                            } else {
                              setSelectedVulnerabilities(selectedVulnerabilities.filter(v => v !== vuln));
                            }
                          }}
                          style={{ marginRight: "0.5rem" }}
                        />
                        {vuln}
                      </label>
                    ))}
                  </div>
                </div>
                
                <div style={{ marginBottom: "1.5rem" }}>
                  <label style={{ display: "block", marginBottom: "0.5rem" }}>
                    Атаки · выбрано: {selectedAttacks.length}
                  </label>
                  <div style={{ 
                    maxHeight: "150px", 
                    overflow: "auto", 
                    border: "0.1rem solid var(--separator-default)", 
                    borderRadius: "var(--radius-m)",
                    padding: "0.5rem"
                  }}>
                    {DEEPTEAM_ATTACKS.map((attack) => (
                      <label key={attack} style={{ display: "block", marginBottom: "0.25rem", fontSize: "0.9rem" }}>
                        <input
                          type="checkbox"
                          checked={selectedAttacks.includes(attack)}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setSelectedAttacks([...selectedAttacks, attack]);
                            } else {
                              setSelectedAttacks(selectedAttacks.filter(a => a !== attack));
                            }
                          }}
                          style={{ marginRight: "0.5rem" }}
                        />
                        {attack}
                      </label>
                    ))}
                  </div>
                </div>
              </>
            )}
            
            {createError && (
              <p style={{ color: "var(--danger)", margin: "0 0 1rem" }}>Не удалось создать сканирование: {createError}</p>
            )}
            <div style={{ display: "flex", gap: "1rem", justifyContent: "flex-end" }}>
              <button className="btn btn-secondary" onClick={() => setShowCreateModal(false)}>
                Отмена
              </button>
              <button
                className="btn btn-primary"
                onClick={handleCreateScan}
                disabled={!canCreate}
              >
                Создать
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
