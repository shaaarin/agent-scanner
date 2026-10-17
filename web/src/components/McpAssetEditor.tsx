import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { McpAsset, MCPArtifact, MCPTransport } from "../api/types";

function objectValue(raw: string, label: string, stringsOnly = false): Record<string, unknown> {
  let value: unknown;
  try { value = JSON.parse(raw); } catch { throw new Error(`${label}: некорректный JSON`); }
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error(`${label}: нужен JSON-объект`);
  if (stringsOnly && !Object.values(value).every(v => typeof v === "string")) throw new Error(`${label}: значения должны быть строками`);
  return value as Record<string, unknown>;
}

function JsonSetting({label, value, onChange}: {label: string; value: string; onChange: (value: string) => void}) {
  return <label className="field">{label}<textarea aria-label={label} rows={3} value={value} onChange={e => onChange(e.target.value)} spellCheck={false} /></label>;
}

export function McpAssetEditor({asset, onSaved, onCancel}: {asset: McpAsset; onSaved: () => void; onCancel: () => void}) {
  const form = useRef<HTMLFormElement>(null);
  const [name, setName] = useState(asset.name);
  const [description, setDescription] = useState(asset.description ?? "");
  const [target, setTarget] = useState(asset.config);
  const [headers, setHeaders] = useState(JSON.stringify(asset.config.kind === "remote" ? asset.config.headers : {}, null, 2));
  const [env, setEnv] = useState(JSON.stringify(asset.config.kind === "repository" ? asset.config.env : {}, null, 2));
  const [userConfig, setUserConfig] = useState(JSON.stringify(asset.config.kind === "bundle" ? asset.config.user_config : {}, null, 2));
  const [deployEnabled, setDeployEnabled] = useState(asset.deploy !== null);
  const [port, setPort] = useState(asset.deploy?.port == null ? "" : String(asset.deploy.port));
  const [command, setCommand] = useState(asset.deploy?.command ?? "");
  const [dockerfile, setDockerfile] = useState(asset.deploy?.dockerfile_path ?? "");
  const [mcpPath, setMcpPath] = useState(asset.deploy?.mcp_path ?? "");
  const [deployEnv, setDeployEnv] = useState(JSON.stringify(asset.deploy?.env ?? {}, null, 2));
  const [artifact, setArtifact] = useState<MCPArtifact | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [bundleUrl, setBundleUrl] = useState("");
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { form.current?.scrollIntoView({behavior: "smooth", block: "start"}); }, []);
  const artifactId = target.kind === "bundle" ? target.artifact_id : null;
  useEffect(() => {
    let cancelled = false;
    if (artifactId !== null) {
      api.get<MCPArtifact>(`/mcp-artifacts/${artifactId}`).then(value => {if (!cancelled) setArtifact(value);}).catch(() => {});
    }
    return () => {cancelled = true;};
  }, [artifactId]);

  const replaceBundle = async () => {
    if (target.kind !== "bundle") return;
    setUploading(true); setError(null);
    try {
      let next: MCPArtifact;
      if (file) {
        const body = new FormData(); body.append("file", file);
        next = await api.postForm<MCPArtifact>("/mcp-artifacts/upload", body);
      } else {
        next = await api.post<MCPArtifact>("/mcp-artifacts/from-url", {url: bundleUrl.trim()});
      }
      setArtifact(next); setTarget({...target, artifact_id: next.id});
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setUploading(false); }
  };

  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      let config = {...target};
      if (config.kind === "remote") config = {...config, headers: objectValue(headers, "Заголовки", true) as Record<string, string>};
      if (config.kind === "repository") config = {...config, env: objectValue(env, "Окружение", true) as Record<string, string>};
      if (config.kind === "bundle") config = {...config, user_config: objectValue(userConfig, "Настройки MCPB")};
      const deploy = target.kind === "remote" ? asset.deploy : !deployEnabled ? null : {
        port: port ? Number(port) : null, command: command.trim() || null,
        dockerfile_path: dockerfile.trim() || null, mcp_path: mcpPath.trim() || null,
        env: objectValue(deployEnv, "Окружение деплоя", true),
      };
      await api.put(`/mcp-assets/${asset.id}`, {name: name.trim(), description: description.trim() || null, config, deploy});
      onSaved();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  return <form ref={form} className="card asset-edit-form" onSubmit={save} aria-label="Редактирование MCP-актива">
    <h2>Изменить MCP-актив</h2>
    <p>Изменения применяются к новым сканированиям. Настройки уже созданных сканов сохраняются.</p>
    <fieldset disabled={busy || uploading}>
      <label className="field">Название<input required value={name} onChange={e => setName(e.target.value)} /></label>
      <label className="field">Описание<textarea aria-label="Описание" rows={2} value={description} onChange={e => setDescription(e.target.value)} /></label>
      {target.kind === "remote" && <>
        <label className="field">Адрес MCP-сервера<input type="url" required value={target.server_url} onChange={e => setTarget({...target, server_url: e.target.value})} /></label>
        <label className="field">Транспорт MCP<select aria-label="Транспорт MCP" value={target.transport} onChange={e => setTarget({...target, transport: e.target.value as MCPTransport})}>
          <option value="auto">Автоопределение</option><option value="streamable_http">Streamable HTTP</option><option value="sse">Legacy SSE</option>
        </select></label>
        <JsonSetting label="Заголовки авторизации и дополнительные заголовки (JSON)" value={headers} onChange={setHeaders} />
        <label className="checkbox-setting"><input type="checkbox" checked={target.verify_tls} onChange={e => setTarget({...target, verify_tls: e.target.checked})} />Проверять TLS-сертификат</label>
      </>}
      {target.kind === "repository" && <>
        <label className="field">URL Git-репозитория<input required type="url" value={target.git_repo_url} onChange={e => setTarget({...target, git_repo_url: e.target.value})} /></label>
        <label className="field">Ветка, тег или commit<input required value={target.git_ref} onChange={e => setTarget({...target, git_ref: e.target.value})} /></label>
        <label className="field">Токен доступа к Git<input type="password" autoComplete="off" value={target.git_access_token ?? ""} onChange={e => setTarget({...target, git_access_token: e.target.value || null})} /></label>
        <label className="field">Путь к конфигурации MCP<input required value={target.config_path} onChange={e => setTarget({...target, config_path: e.target.value})} /></label>
        <JsonSetting label="Переменные окружения (JSON)" value={env} onChange={setEnv} />
      </>}
      {target.kind === "bundle" && <>
        <p>Архив: {artifact?.original_filename ?? `MCPB №${target.artifact_id}`}</p>
        <label className="field">Новый MCPB-файл<input type="file" accept=".mcpb,application/zip" onChange={e => setFile(e.target.files?.[0] ?? null)} /></label>
        <label className="field">Или HTTPS URI нового архива<input type="url" value={bundleUrl} onChange={e => setBundleUrl(e.target.value)} placeholder="https://example.com/server.mcpb" /></label>
        <button type="button" className="btn btn-secondary" disabled={!file && !bundleUrl.trim()} onClick={replaceBundle}>Загрузить и проверить новый архив</button>
        <JsonSetting label="Пользовательская конфигурация MCPB (JSON)" value={userConfig} onChange={setUserConfig} />
      </>}
      {target.kind !== "remote" && <>
        <label className="checkbox-setting"><input type="checkbox" checked={deployEnabled} onChange={e => setDeployEnabled(e.target.checked)} />Настроить деплой</label>
        {deployEnabled && <>
          <label className="field">Порт MCP-сервера<input type="number" min={1} max={65535} value={port} onChange={e => setPort(e.target.value)} /></label>
          <label className="field">Команда запуска<input value={command} onChange={e => setCommand(e.target.value)} /></label>
          <label className="field">Dockerfile<input value={dockerfile} onChange={e => setDockerfile(e.target.value)} /></label>
          <label className="field">URL path к MCP<input value={mcpPath} onChange={e => setMcpPath(e.target.value)} /></label>
          <JsonSetting label="Переменные окружения деплоя (JSON)" value={deployEnv} onChange={setDeployEnv} />
        </>}
      </>}
    </fieldset>
    {error && <p role="alert" style={{color: "var(--status-negative)"}}>{error}</p>}
    {uploading && <p role="status">Загрузка и проверка архива…</p>}
    <div className="asset-form-actions">
      <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={busy || uploading}>Отмена</button>
      <button className="btn btn-primary" disabled={busy || uploading || !name.trim()}>{busy ? "Сохранение…" : "Сохранить изменения"}</button>
    </div>
  </form>;
}
