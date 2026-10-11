import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Scan } from "../api/types";
import { PageHeader } from "../components/PageHeader";

type Engine = { id: string; name: string; kind: string; version: string; description: string; source: string; cloud: boolean; modes: string[]; available: boolean; reason?: string };
const sampleTools = JSON.stringify({tools: [{name: "echo", description: "Echo the text supplied by the caller.", inputSchema: {type: "object", properties: {text: {type: "string"}}, required: ["text"]}}]}, null, 2);
const vulnerable = `from mcp.server.fastmcp import FastMCP\nimport os\nimport subprocess\nmcp = FastMCP("example")\n\n@mcp.tool()\ndef calculate(expression: str):\n    return eval(expression)\n\n@mcp.tool()\ndef run_command(command: str):\n    return subprocess.check_output(command, shell=True)\n\n@mcp.tool()\ndef read_file(path: str):\n    return open(path).read()\n\n@mcp.tool()\ndef environment():\n    return dict(os.environ)\n`;
const safe = `from mcp.server.fastmcp import FastMCP\nmcp = FastMCP("safe")\n\n@mcp.tool()\ndef add(a: int, b: int):\n    return a + b\n`;
const modeNames: Record<string, string> = { snapshot: "Каталог tools/list (JSON)", remote: "Работающий MCP-сервер", source: "Исходный код", repository: "Git-репозиторий (HTTPS)" };
const kindNames: Record<string, string> = { metadata: "Анализ каталога", readiness: "Готовность", dynamic: "Динамическое тестирование", sast: "Статическое тестирование / SAST" };

export function MCPScanners() {
  const navigate = useNavigate();
  const [engines, setEngines] = useState<Engine[]>([]);
  const [engineId, setEngineId] = useState("semgrep");
  const [mode, setMode] = useState("source");
  const [name, setName] = useState("MCP · статическая проверка");
  const [source, setSource] = useState(vulnerable);
  const [filename, setFilename] = useState("server.py");
  const [tools, setTools] = useState(sampleTools);
  const [url, setUrl] = useState("http://mcp-test-target:8000/mcp");
  const [transport, setTransport] = useState("streamable_http");
  const [repo, setRepo] = useState("");
  const [ref, setRef] = useState("main");
  const [probes, setProbes] = useState(JSON.stringify([{tool: "echo", arguments: {text: "mcp-probe-123"}, contains: "mcp-probe-123"}, {tool: "add", arguments: {a: 2, b: 3}, contains: "5"}], null, 2));
  const [calls, setCalls] = useState(false);
  const [cloud, setCloud] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const engine = engines.find(e => e.id === engineId);

  useEffect(() => { api.get<Engine[]>("/mcp-scanners").then(setEngines).catch(e => setError(String(e))); }, []);
  const select = (e: Engine) => {
    setEngineId(e.id); setMode(e.modes[0]); setCloud(false); setCalls(false); setError(null);
    setName(`MCP · ${kindNames[e.kind]}`);
  };
  const start = async () => {
    if (!engine) return;
    setBusy(true); setError(null);
    try {
      const config: Record<string, unknown> = {engine: engine.id, mode};
      if (mode === "source") config.files = {[filename]: source};
      if (mode === "repository") { config.repository_url = repo; config.git_ref = ref; }
      if (mode === "snapshot") config.tools = JSON.parse(tools);
      if (mode === "remote") { config.server_url = url; config.transport = transport; }
      if (engine.id === "snyk") config.allow_cloud = cloud;
      if (engine.id === "mcp_dynamic") { config.probes = JSON.parse(probes); config.allow_tool_calls = calls; }
      const scan = await api.post<Scan>("/scans", {name, type: "mcp", status: "pending", session_id: `mcp-${crypto.randomUUID()}`, config: JSON.stringify(config)});
      await api.post(`/scans/${scan.id}/start`, {});
      navigate(`/scans/${scan.id}`);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  return <div>
    <PageHeader title="MCP-сканеры" description="Статическое и динамическое тестирование MCP, анализ каталогов и результаты проверок." />
    <p><Link to="/help">Справка: выбор сканера, примеры и результаты →</Link></p>
    <div style={{display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "1rem", marginBottom: "2rem"}}>
      {engines.map(e => <div className="card" key={e.id} style={{padding: "1.5rem", border: engineId === e.id ? "2px solid var(--brand)" : undefined}}>
        <span className={`badge ${e.available ? "badge-success" : "badge-secondary"}`}>{e.available ? "Подключён" : "Недоступен"}</span>
        <h3 style={{margin: "1rem 0 .5rem"}}>{e.name}</h3>
        <p style={{color: "var(--text-500)", fontSize: 13}}>{kindNames[e.kind]} · {e.version} · {e.cloud ? "Облако" : "Локально"}</p>
        <p>{e.description}</p>
        {e.reason && <p>{e.reason}</p>}
        <div style={{display: "flex", gap: "1rem", alignItems: "center"}}><button className="btn btn-secondary" onClick={() => select(e)}>{engineId === e.id ? "Выбран" : "Выбрать"}</button><a href={e.source} target="_blank" rel="noreferrer">Документация</a></div>
      </div>)}
    </div>
    <div className="card" style={{padding: "2rem"}}>
      <h2>{engine?.name ?? "Загрузка сканеров…"}</h2>
      <p style={{color: "var(--text-500)"}}>Для проверки доступны готовые примеры. Исходники анализируются без исполнения; динамические вызовы выполняются только для указанных инструментов.</p>
      <div style={{display: "flex", gap: ".5rem", flexWrap: "wrap", marginBottom: "1.5rem"}}>
        <button className="btn btn-secondary" onClick={() => {setEngineId("semgrep"); setMode("source"); setSource(vulnerable); setFilename("server.py"); setName("Пример · MCP SAST · проблемный код");}}>Пример: проблемный код</button>
        <button className="btn btn-secondary" onClick={() => {setEngineId("semgrep"); setMode("source"); setSource(safe); setFilename("server.py"); setName("Пример · MCP SAST · исправленный код");}}>Пример: исправленный код</button>
        <button className="btn btn-secondary" onClick={() => {setEngineId("mcp_dynamic"); setMode("remote"); setUrl("http://mcp-test-target:8000/mcp"); setName("Пример · динамическое MCP-тестирование");}}>Пример: живой MCP-сервер</button>
      </div>
      <label style={{display: "block", marginBottom: "1rem"}}>Название<input aria-label="Название MCP-сканирования" className="input" style={{width: "100%"}} value={name} onChange={e=>setName(e.target.value)} /></label>
      <label style={{display: "block", marginBottom: "1rem"}}>Источник проверки<select aria-label="Источник проверки" className="input" style={{width: "100%"}} value={mode} onChange={e=>setMode(e.target.value)}>{engine?.modes.map(m=><option key={m} value={m}>{modeNames[m]}</option>)}</select></label>
      {mode === "source" && <><label style={{display: "block"}}>Имя файла<input aria-label="Имя файла" className="input" value={filename} onChange={e=>setFilename(e.target.value)} /></label><label style={{display: "block", marginTop: "1rem"}}>Исходный код<textarea aria-label="Исходный код MCP" className="input" rows={16} style={{width: "100%", fontFamily: "monospace"}} value={source} onChange={e=>setSource(e.target.value)} /></label></>}
      {mode === "repository" && <><label>HTTPS URL репозитория<input aria-label="URL репозитория" className="input" style={{width: "100%"}} value={repo} onChange={e=>setRepo(e.target.value)} placeholder="https://github.com/organization/mcp-server.git" /></label><label>Ветка<input aria-label="Ветка" className="input" value={ref} onChange={e=>setRef(e.target.value)} /></label><p>Публичный HTTPS-репозиторий. Код не выполняется и не отправляется в облако.</p></>}
      {mode === "snapshot" && <label>Каталог MCP<textarea aria-label="Каталог MCP JSON" className="input" rows={12} style={{width: "100%", fontFamily: "monospace"}} value={tools} onChange={e=>setTools(e.target.value)} /></label>}
      {mode === "remote" && <><label>URL MCP-сервера<input aria-label="URL MCP-сервера" className="input" style={{width: "100%"}} value={url} onChange={e=>setUrl(e.target.value)} /></label><label>Транспорт<select aria-label="Транспорт MCP" className="input" value={transport} onChange={e=>setTransport(e.target.value)}><option value="streamable_http">Streamable HTTP</option><option value="sse">SSE</option></select></label><p>Локальный стенд: http://mcp-test-target:8000/mcp. Сервис на Mac: используйте host.docker.internal вместо localhost.</p></>}
      {engineId === "mcp_dynamic" && <><label>Пробные вызовы (JSON)<textarea aria-label="Пробные вызовы" className="input" rows={10} style={{width: "100%", fontFamily: "monospace"}} value={probes} onChange={e=>setProbes(e.target.value)} /></label><p>Проверки ответа: contains, forbidden, expect_error. Пустой список [] выполнит только инициализацию и проверку каталога.</p><label><input type="checkbox" checked={calls} onChange={e=>setCalls(e.target.checked)} /> Разрешаю указанные вызовы на своём тестовом MCP-сервере</label></>}
      {engine?.cloud && <label><input type="checkbox" checked={cloud} onChange={e=>setCloud(e.target.checked)} /> Передать каталог MCP в Snyk для анализа</label>}
      {error && <p role="alert" style={{color: "var(--danger)"}}>{error}</p>}
      <div style={{marginTop: "1.5rem"}}><button className="btn btn-primary" onClick={start} disabled={busy || !name.trim() || !engine?.available || (engine.cloud && !cloud) || (engineId === "mcp_dynamic" && probes.trim() !== "[]" && !calls)}>{busy ? "Запуск…" : "Запустить MCP-проверку"}</button></div>
    </div>
  </div>;
}
