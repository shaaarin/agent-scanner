import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Scan, ScanType, AgentConfig, LLMModel, CodeScanSeverity } from "../api/types";
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
  const [injectionTasks, setInjectionTasks] = useState("");
  const [injectionRepeats, setInjectionRepeats] = useState(1);
  const [injectionMaxTrials, setInjectionMaxTrials] = useState(60);
  const [pageError, setPageError] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);

  // Модель-судья нужна только динамическому тестированию (DeepTeam).
  const needsLlmModel = newScanType === "deep_team";
  const canCreate = Boolean(newScanName && selectedAgentId && (!needsLlmModel || selectedLlmModelId));

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

  const handleCreateScan = async () => {
    if (!canCreate) return;

    const config: Record<string, unknown> = {};

    if (newScanType === "deep_team") {
      config.eval_llm_model_id = selectedLlmModelId;
      config.vulnerabilities = selectedVulnerabilities.length > 0 ? selectedVulnerabilities : ["BFLA", "BOLA", "RBAC"];
      config.attacks = selectedAttacks.length > 0 ? selectedAttacks : ["PromptInjection"];
    } else if (newScanType === "code_scan") {
      config.min_severity = minSeverity;
      config.guidance = guidance.trim() || null;
    } else if (newScanType === "indirect_injection") {
      config.tasks = injectionTasks
        .split("\n")
        .map((t) => t.trim())
        .filter(Boolean);
      config.repeats = injectionRepeats;
      config.max_trials = injectionMaxTrials;
    }

    setCreateError(null);
    try {
      await api.post("/scans", {
        name: newScanName,
        type: newScanType,
        agent_config_id: selectedAgentId,
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
      setInjectionTasks("");
      setInjectionRepeats(1);
      setInjectionMaxTrials(60);
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
                : newScanType === "indirect_injection"
                ? "Платформа запустит агента, отправит ему легитимную задачу и во время работы подложит инъекцию в результаты его инструментов, проверяя, поддаётся ли агент."
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
                <option value="indirect_injection">Косвенные инъекции</option>
                <option value="mcp">MCP (в разработке)</option>
                <option value="agent_skills">Agent Skills (в разработке)</option>
              </select>
            </div>
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

            {newScanType === "indirect_injection" && (
              <>
                <div style={{ marginBottom: "1rem" }}>
                  <label style={{ display: "block", marginBottom: "0.5rem" }}>Легитимные задачи (по одной в строке)</label>
                  <textarea
                    className="input"
                    value={injectionTasks}
                    onChange={(e) => setInjectionTasks(e.target.value)}
                    placeholder={"Проверьте статус заказа ORD-1002\nОформите возврат по заказу ORD-1001"}
                    rows={4}
                    style={{ width: "100%", resize: "vertical" }}
                  />
                  <p style={{ margin: "0.4rem 0 0", fontSize: 12, color: "var(--text-500)" }}>
                    Каждая задача должна приводить к вызову инструмента. Если оставить пусто — задача подставится по назначению агента.
                  </p>
                </div>
                <div style={{ display: "flex", gap: "1rem", marginBottom: "1.5rem" }}>
                  <div style={{ flex: 1 }}>
                    <label style={{ display: "block", marginBottom: "0.5rem" }}>Повторов на комбинацию</label>
                    <input
                      type="number"
                      className="input"
                      min={1}
                      max={10}
                      value={injectionRepeats}
                      onChange={(e) => setInjectionRepeats(Math.max(1, Number(e.target.value)))}
                      style={{ width: "100%" }}
                    />
                    <p style={{ margin: "0.4rem 0 0", fontSize: 12, color: "var(--text-500)" }}>
                      Ответы недетерминированы — повторы дают долю успеха.
                    </p>
                  </div>
                  <div style={{ flex: 1 }}>
                    <label style={{ display: "block", marginBottom: "0.5rem" }}>Лимит прогонов</label>
                    <input
                      type="number"
                      className="input"
                      min={1}
                      max={500}
                      value={injectionMaxTrials}
                      onChange={(e) => setInjectionMaxTrials(Math.max(1, Number(e.target.value)))}
                      style={{ width: "100%" }}
                    />
                    <p style={{ margin: "0.4rem 0 0", fontSize: 12, color: "var(--text-500)" }}>
                      Каждый прогон — реальный вызов LLM.
                    </p>
                  </div>
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