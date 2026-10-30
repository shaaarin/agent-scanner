import asyncio
import json
import os
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

from app.process import execute
from app.target import bundle_extract, bundle_inspect, inspect, dynamic, validate_url


def cisco(c, work):
    if c["mode"] == "snapshot":
        tools = c.get("tools")
    elif c["mode"] == "bundle":
        tools = asyncio.run(bundle_inspect(c))
    else:
        tools = asyncio.run(inspect(c))
    if not tools or not tools.get("tools"):
        raise ValueError("Пустой каталог MCP")
    path = work / "tools.json"
    path.write_text(json.dumps(tools))
    analyzer = {"cisco_yara": "yara", "cisco_readiness": "readiness", "cisco_prompt_defense": "prompt_defense"}[c["engine"]]
    command = ["/opt/cisco/bin/mcp-scanner", "--analyzers", analyzer, "--format", "raw", "--log-level", "error", "static", "--tools", str(path)] if analyzer == "yara" else ["/opt/cisco/bin/python", "/srv/app/cisco_sdk.py", analyzer, str(path)]
    rc, stdout, stderr = execute(command, cwd=work, timeout=min(240, c.get("timeout_seconds", 300)))
    if rc != 0:
        raise RuntimeError(f"Cisco CLI завершился с кодом {rc}: {stderr[-1200:]}")
    raw = json.loads(stdout)
    if isinstance(raw, dict):
        raw["server_url"] = c.get("server_url")  # Cisco static CLI supplies a placeholder URL.
    # CLI raw output differs from the public HTTP grouping model; fail closed
    # until the report is recognized, rather than inventing a clean scan.
    entries = raw if isinstance(raw, list) else raw.get("scan_results", raw.get("results")) if isinstance(raw, dict) else None
    if entries is None:
        raise ValueError("Неизвестная схема Cisco JSON")
    findings, errors = [], []
    for entry in entries:
        errors.extend(entry.get("analyzer_errors", []))
        if entry.get("status", "").lower() in {"error", "failed"}:
            errors.append(entry.get("status"))
        for engine, values in entry.get("findings", {}).items():
            if isinstance(values, dict):
                values = values.get("findings", [values])
            for f in values:
                if not isinstance(f, dict):
                    raise ValueError("Неизвестная схема находки Cisco")
                if str(f.get("severity", "")).lower() in {"safe", "info", "informational", "none"}:
                    continue
                findings.append(dict(rule_id=f.get("rule_id", f.get("threat_category", engine)), severity=str(f.get("severity", "medium")).lower(), title=f.get("summary") or f.get("threat_summary") or f.get("description") or ", ".join(f.get("threat_names", [])) or engine, target=entry.get("tool_name", "MCP"), evidence=f.get("details") or f.get("description") or f.get("summary") or json.dumps(f, ensure_ascii=False), recommendation=f.get("remediation") or "Проверьте описание, схему и реализацию MCP-инструмента.", category="readiness" if analyzer == "readiness" else "metadata"))
    if errors:
        raise RuntimeError("Ошибка анализатора Cisco: " + json.dumps(errors, ensure_ascii=False)[:1200])
    return dict(findings=findings, tools_checked=len(tools["tools"]), raw=raw, coverage=f"Локальный Cisco {analyzer}: каталог инструментов. Не выполняет инструменты и не доказывает безопасность реализации.")


def mcpradar(c, work):
    if c["mode"] == "snapshot":
        tools = c.get("tools")
    elif c["mode"] == "bundle":
        tools = asyncio.run(bundle_inspect(c))
    else:
        tools = asyncio.run(inspect(c))
    path = work / "tools.json"
    path.write_text(json.dumps(tools))
    rc, stdout, stderr = execute(["/opt/mcpradar/bin/python", "/srv/app/radar_sdk.py", str(path)], cwd=work, timeout=min(180, c.get("timeout_seconds", 300)))
    if rc:
        raise RuntimeError("MCPRadar: " + stderr[-1200:])
    raw = json.loads(stdout)
    if not isinstance(raw.get("findings"), list) or raw.get("tools_checked", 0) < 1:
        raise ValueError("MCPRadar не вернул проверенный каталог")
    findings = [dict(f, recommendation="Проверьте описание, схему и реализацию инструмента; сигнатурная находка требует подтверждения.", category="metadata") for f in raw["findings"]]
    return dict(findings=findings, tools_checked=raw["tools_checked"], raw=raw, coverage="MCPRadar 1.0.0rc4 RuleEngine: локальные правила для tools/list. Каталог получен MCP SDK платформы. Без runtime probes, зависимостей, prompts/resources и анализа исходников; API этих возможностей отличается от текущей main-ветки upstream.")


def snyk(c, work):
    if not c.get("allow_cloud"):
        raise ValueError("Не подтверждена передача каталога в Snyk")
    if not os.getenv("SNYK_TOKEN"):
        raise ValueError("Не настроен SNYK_TOKEN")
    if c.get("headers"):
        raise ValueError("Snyk: пользовательские заголовки пока не поддерживаются")
    validate_url(c["server_url"])
    config = {"mcpServers": {"target": {"url": c["server_url"], "type": "sse" if c.get("transport") == "sse" else "http"}}}
    file = work / "mcp.json"
    file.write_text(json.dumps(config))
    rc, stdout, _ = execute(["/opt/snyk/bin/snyk-agent-scan", "scan", "--json", "--no-skills", "--ci", "--dangerously-run-mcp-servers", "--storage-file", str(work / "state.json"), str(file)], timeout=min(300, c.get("timeout_seconds", 300)), cwd=work, env={"SNYK_TOKEN": os.environ["SNYK_TOKEN"]})
    raw = json.loads(stdout)
    if not isinstance(raw, dict) or not isinstance(raw.get("scan_path_responses"), list):
        raise ValueError("Неизвестная схема Snyk JSON")
    findings, count = [], 0
    for path in raw["scan_path_responses"]:
        if path.get("error"):
            raise RuntimeError("Snyk: ошибка анализа пути")
        for server in path.get("server_risks", []):
            if server.get("error"):
                raise RuntimeError("Snyk: ошибка подключения или анализа сервера")
            count += 1
            for name, risk in server.get("risk_indexes", {}).items():
                if risk.get("score", 0) <= 0:
                    continue
                findings.append(dict(rule_id=name, severity="high" if risk["score"] >= 700 else "medium" if risk["score"] >= 400 else "low", title=name, target=server["name"], evidence=risk.get("evidence", ""), recommendation="Проверьте отмеченные описания и инструменты; оценка Snyk — индикатор риска, а не подтверждение эксплуатации.", category="metadata", score=risk["score"]))
    if not count or rc not in {0, 1} or (rc == 1 and not findings):
        raise RuntimeError("Snyk не вернул успешно проанализированный MCP-сервер")
    return dict(findings=findings, raw=raw, coverage="Облачный анализ каталога Snyk. Балл риска 0–1000; уровни серьёзности отображены по порогам платформы.")


def sast(c, work):
    root = work / "source"
    root.mkdir()
    commit = None
    if c["mode"] == "bundle":
        manifest = bundle_extract(c, root, code_only=True)
    elif c["mode"] == "repository":
        # Валидируем чистый URL; токен подставляем в netloc по конвенции
        # GitLab (oauth2:<token>@host), как в launcher/app/git_auth.py.
        url = validate_url(c["repository_url"])
        if urlsplit(url).scheme != "https":
            raise ValueError("Репозитории принимаются только по HTTPS")
        # GitLab отдаёт редирект на ...git, а редиректы запрещены (защита
        # токена от утечки на чужой хост) -- нормализуем суффикс.
        if not url.rstrip("/").endswith(".git"):
            url = url.rstrip("/") + ".git"
        clone_url = url
        token = c.get("git_access_token")
        if token:
            # urlunparse в 3.13 спотыкается о SplitResult -- подставляем строкой.
            clone_url = url.replace("https://", f"https://oauth2:{quote(token)}@", 1)
        rc, _, _ = execute(["git", "-c", "http.followRedirects=false", "-c", "protocol.file.allow=never", "clone", "--depth", "1", "--single-branch", "--branch", c.get("git_ref", "main"), "--", clone_url, str(root)], timeout=min(120, c.get("timeout_seconds", 300)))
        if rc:
            raise RuntimeError("Не удалось клонировать репозиторий. Проверьте HTTPS URL, токен доступа и ветку.")
        _, commit, _ = execute(["git", "rev-parse", "HEAD"], cwd=root)
        commit = commit.strip()
    else:
        files = c.get("files", {})
        if not files or len(files) > 100 or sum(len(v) for v in files.values()) > 1_000_000:
            raise ValueError("Нужны исходники: до 100 файлов / 1 МБ")
        for name, content in files.items():
            path = root / name
            if Path(name).is_absolute() or ".." in Path(name).parts or path.suffix not in {".py", ".js", ".ts", ".tsx", ".jsx"}:
                raise ValueError("Недопустимый путь исходного файла")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    # Do not follow symlinks or scan vendored/dependency trees.
    for p in root.rglob("*"):
        if p.is_symlink():
            p.unlink()
    args = ["/opt/semgrep/bin/semgrep", "scan", "--config", "/srv/rules/mcp-security.yml", "--json", "--metrics=off", "--disable-version-check", "--no-git-ignore", "--strict", "--timeout", "10", "--max-target-bytes", "1000000", "--exclude", "node_modules", "--exclude", ".git", "--exclude", ".venv", "."]
    rc, stdout, stderr = execute(args, cwd=root, timeout=min(180, c.get("timeout_seconds", 300)))
    raw = json.loads(stdout)
    if rc != 0 or raw.get("errors"):
        raise RuntimeError("Semgrep не выполнил полный анализ: " + json.dumps(raw.get("errors", []), ensure_ascii=False)[:1200])
    scanned = raw.get("paths", {}).get("scanned", [])
    if not scanned:
        raise ValueError("Не найдены поддерживаемые Python/JS/TS исходники")
    findings = [dict(rule_id=f["check_id"], severity="high" if f["extra"]["severity"] == "ERROR" else "medium", title=f["extra"]["message"], target=f["path"], file=f["path"], line=f["start"]["line"], evidence=f["extra"].get("lines", ""), recommendation=f["extra"]["message"], category="sast", confidence=f["extra"].get("metadata", {}).get("confidence", "MEDIUM")) for f in raw.get("results", [])]
    return dict(findings=findings, files_checked=len(scanned), commit=commit, raw=raw, coverage="6 MCP-правил AST, Python @*.tool и JS/TS tool/registerTool. Нет межфайлового taint, доказательства авторизации и полного покрытия async/обёрток. Отсутствие находок не доказывает безопасность.")


async def run_mcp_dynamic(c):
    """Динамика: для remote -- по HTTP, для MCPB -- деплой по манифесту
    (установка зависимостей, запуск сервера) и сеанс по stdio."""
    import tempfile
    c = {**c, "_dynamic_deadline": time.monotonic() + max(0, c.get("timeout_seconds", 30)-5)}
    from app.target import dynamic, run_dynamic, stdio_session_for_bundle
    if c["mode"] == "bundle":
        with tempfile.TemporaryDirectory(prefix="mcp-bundle-") as tmp:
            root = Path(tmp) / "bundle"
            root.mkdir()
            manifest = bundle_extract(c, root, code_only=False)
            async with stdio_session_for_bundle(root, manifest, c.get("user_config") or {}) as session:
                return await run_dynamic(session, c)
    return await dynamic(c)


def scan(c, work):
    engine = c["engine"]
    if engine.startswith("cisco_"):
        return cisco(c, work)
    if engine == "mcpradar":
        return mcpradar(c, work)
    if engine == "snyk":
        return snyk(c, work)
    if engine == "semgrep":
        return sast(c, work)
    if engine == "mcp_dynamic":
        return asyncio.run(asyncio.wait_for(run_mcp_dynamic(c), timeout=min(300, c.get("timeout_seconds", 300))))
    raise ValueError("Неизвестный движок")
