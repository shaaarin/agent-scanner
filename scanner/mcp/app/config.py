"""Validate persisted MCP jobs before accepting or launching them."""
import json
from urllib.parse import urlsplit
from fastapi import HTTPException

ENGINES = {"mcpradar", "cisco_yara", "cisco_readiness", "cisco_prompt_defense", "snyk", "mcp_dynamic", "semgrep"}

def validate_flat(raw):
    try:
        c = json.loads(raw)
        if not isinstance(c, dict) or c.get("engine") not in ENGINES:
            raise ValueError("Выберите поддерживаемый MCP-сканер")
        mode = c.get("mode")
        engine = c["engine"]
        if not isinstance(c.get("auto_probes", False), bool):
            raise ValueError("auto_probes должен быть boolean")
        if mode not in {"snapshot", "remote", "source", "repository", "bundle"}:
            raise ValueError("Неизвестный режим MCP-сканирования")
        if engine == "semgrep":
            if mode == "source":
                files = c.get("files")
                if not isinstance(files, dict) or not 1 <= len(files) <= 100:
                    raise ValueError("Добавьте от 1 до 100 исходных файлов")
                if not all(isinstance(k, str) and isinstance(v, str) for k, v in files.items()):
                    raise ValueError("Исходники должны иметь формат {путь: текст}")
                if sum(len(v) for v in files.values()) > 1_000_000:
                    raise ValueError("Исходники превышают 1 МБ")
            elif mode == "repository":
                u = urlsplit(c.get("repository_url", ""))
                if u.scheme != "https" or not u.hostname or u.username or u.password:
                    raise ValueError("Нужен HTTPS URL репозитория без пароля или токена")
                ref = c.get("git_ref", "main")
                if not isinstance(ref, str) or not ref or ref.startswith("-") or len(ref) > 200:
                    raise ValueError("Некорректная ветка")
            elif mode == "bundle":
                if not isinstance(c.get("artifact_id"), int):
                    raise ValueError("Нужен MCPB artifact_id")
            elif mode == "bundle":
                if not isinstance(c.get("artifact_id"), int):
                    raise ValueError("Нужен MCPB artifact_id")
            else:
                raise ValueError("SAST принимает исходники или репозиторий")
        elif mode == "snapshot":
            if engine in {"snyk", "mcp_dynamic"}:
                raise ValueError("Этот движок требует работающий MCP-сервер")
            tools = c.get("tools", {}).get("tools") if isinstance(c.get("tools"), dict) else None
            if not isinstance(tools, list) or not 1 <= len(tools) <= 500:
                raise ValueError("Нужен непустой каталог {tools: [...]} (до 500 инструментов)")
            for t in tools:
                if not isinstance(t, dict) or not isinstance(t.get("name"), str) or not t["name"]:
                    raise ValueError("У каждого инструмента должно быть имя")
                if not isinstance(t.get("inputSchema"), dict):
                    raise ValueError("У каждого инструмента должна быть inputSchema")
            if len(json.dumps(tools)) > 1_000_000:
                raise ValueError("Каталог превышает 1 МБ")
        elif mode == "remote":
            u = urlsplit(c.get("server_url", ""))
            if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password or u.fragment:
                raise ValueError("Нужен HTTP(S) URL MCP-сервера без учётных данных")
            if c.get("transport", "streamable_http") not in {"streamable_http", "sse"}:
                raise ValueError("Поддерживается Streamable HTTP или SSE")
            probes = c.get("probes", [])
            if not isinstance(probes, list) or len(probes) > 20:
                raise ValueError("Допустимо до 20 пробных вызовов")
            for p in probes:
                if not isinstance(p, dict) or not isinstance(p.get("tool"), str) or not isinstance(p.get("arguments"), dict):
                    raise ValueError("Пробный вызов: {tool: имя, arguments: объект}")
            if engine == "mcp_dynamic" and (probes or c.get("auto_probes")) and c.get("allow_tool_calls") is not True:
                raise ValueError("Подтвердите пробные вызовы на тестовом сервере")
        elif mode == "bundle":
            if not isinstance(c.get("artifact_id"), int):
                raise ValueError("Нужен MCPB artifact_id")
            if engine == "semgrep":
                pass  # SAST по исходникам архива
            elif engine in {"mcpradar", "cisco_yara", "cisco_readiness", "cisco_prompt_defense"}:
                pass  # каталог снимается по stdio после деплоя по манифесту
            elif engine == "mcp_dynamic":
                # Деплой по манифесту: сервер запускается и доступен по stdio.
                probes = c.get("probes", [])
                if not isinstance(probes, list) or len(probes) > 20:
                    raise ValueError("Допустимо до 20 пробных вызовов")
                for p in probes:
                    if not isinstance(p, dict) or not isinstance(p.get("tool"), str) or not isinstance(p.get("arguments"), dict):
                        raise ValueError("Пробный вызов: {tool: имя, arguments: объект}")
                if (probes or c.get("auto_probes")) and c.get("allow_tool_calls") is not True:
                    raise ValueError("Подтвердите пробные вызовы на сервере из MCPB")
            else:
                raise ValueError("Для MCPB доступны Semgrep, сканеры каталога и динамическое тестирование")
        else:
            raise ValueError("Для этого движка нужны каталог или MCP URL")
        if engine == "snyk" and c.get("allow_cloud") is not True:
            raise ValueError("Подтвердите передачу каталога MCP в Snyk")
    except (ValueError, TypeError, AttributeError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return c


DEFAULTS = {
    "remote": ["cisco_yara", "cisco_readiness", "cisco_prompt_defense", "mcp_dynamic"],
    "snapshot": ["cisco_yara"],
    "repository": ["semgrep"],
    "source": ["semgrep"],
    "bundle": ["semgrep"],
}

def upgrade_flat(c):
    if "target" in c:
        return c
    engine, mode = c.get("engine"), c.get("mode")
    target = {"kind": mode}
    if mode == "remote":
        target.update(server_url=c.get("server_url"), transport=c.get("transport", "streamable_http"))
    elif mode == "source":
        target["files"] = c.get("files")
    elif mode == "snapshot":
        target["tools"] = c.get("tools")
    elif mode == "repository":
        target.update(git_repo_url=c.get("repository_url"), git_ref=c.get("git_ref", "main"))
    elif mode == "bundle":
        target.update(artifact_id=c.get("artifact_id"), user_config=c.get("user_config", {}))
    return dict(target=target, scanner_ids=[engine], timeout_seconds=300, probes=c.get("probes", []), auto_probes=c.get("auto_probes", False), allow_tool_calls=c.get("allow_tool_calls", False), allow_cloud=c.get("allow_cloud", False))

def plan(c):
    c = upgrade_flat(c)
    t = c["target"]
    mode = t["kind"]
    ids = c.get("scanner_ids") or DEFAULTS.get(mode, [])
    tasks = []
    for engine in ids:
        task = dict(engine=engine, mode=mode, timeout_seconds=c.get("timeout_seconds", 300), allow_cloud=c.get("allow_cloud", False), allow_tool_calls=c.get("allow_tool_calls", False), probes=c.get("probes", []), auto_probes=c.get("auto_probes", False))
        if mode == "remote":
            task.update(server_url=t["server_url"], transport="streamable_http" if t.get("transport", "auto") == "auto" else t["transport"], headers=t.get("headers", {}), verify_tls=t.get("verify_tls", True))
        elif mode == "repository":
            task.update(repository_url=t["git_repo_url"], git_ref=t.get("git_ref", "main"), git_access_token=t.get("git_access_token"))
        elif mode == "bundle":
            # The bundle runtime consumes these settings as its environment.
            task.update(artifact_id=t["artifact_id"], user_config=t.get("user_config", {}))
        else:
            task.update({k: v for k,v in t.items() if k != "kind"})
        tasks.append(task)
    return tasks

def validate_mcp_config(raw):
    c = json.loads(raw)
    tasks = plan(c)
    if not tasks:
        raise HTTPException(status_code=422, detail="Нет совместимых сканеров")
    for task in tasks:
        validate_flat(json.dumps(task))
        if task.get("verify_tls") is False:
            raise HTTPException(status_code=422, detail="MCP-сканер требует проверку TLS-сертификата")
    return c
