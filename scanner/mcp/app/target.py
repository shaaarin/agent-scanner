import asyncio
import hashlib
import ipaddress
import json
import os
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client


def validate_url(value):
    u = urlsplit(value)
    if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password or u.fragment:
        raise ValueError("Некорректный URL цели")
    if u.hostname.lower() in {"control-api", "launcher", "scanner-mcp", "scanner-promptfoo", "scanner-deepteam", "metadata.google.internal"}:
        raise ValueError("Адрес служебного компонента запрещён")
    for family, _, _, _, address in socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80), type=socket.SOCK_STREAM):
        ip = ipaddress.ip_address(address[0])
        if ip.is_link_local or ip.is_unspecified or ip.is_multicast or str(ip) in {"100.100.100.200", "fd00:ec2::254"}:
            raise ValueError("Служебные metadata/link-local адреса запрещены")
    return value


def http_client_factory(headers=None, timeout=None, auth=None):
    return httpx.AsyncClient(headers=headers, timeout=timeout or 20, auth=auth, follow_redirects=False)


@asynccontextmanager
async def session_for(c):
    url = validate_url(c["server_url"])
    def factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(headers=headers, timeout=timeout or 20, auth=auth, follow_redirects=False, verify=True)
    headers = c.get("headers", {})
    if any(k.lower() in {"host", "connection", "transfer-encoding", "content-length"} or "\n" in k or "\r" in k or "\n" in v or "\r" in v for k,v in headers.items()):
        raise ValueError("Недопустимый HTTP заголовок")
    if c.get("transport") == "sse":
        transport = sse_client(url, timeout=15, sse_read_timeout=30, httpx_client_factory=factory, headers=headers)
    else:
        transport = streamablehttp_client(url, timeout=__import__('datetime').timedelta(seconds=20), httpx_client_factory=factory, headers=headers)
    async with transport as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            yield session


async def list_tools(session):
    tools, cursor, seen = [], None, set()
    for _ in range(25):
        page = await session.list_tools(cursor=cursor)
        tools.extend(t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in page.tools)
        if len(tools) > 500:
            raise ValueError("Сервер объявляет больше 500 инструментов")
        cursor = page.nextCursor
        if not cursor:
            break
        if cursor in seen:
            raise ValueError("MCP вернул повторяющийся курсор")
        seen.add(cursor)
    else:
        raise ValueError("Превышен лимит страниц tools/list")
    if not tools:
        raise ValueError("MCP не объявил ни одного инструмента")
    return tools


async def inspect(c):
    async with session_for(c) as session:
        tools = await list_tools(session)
        return {"tools": tools}


def bundle_extract(c, root, code_only: bool):
    """Скачивает MCPB из control-api, проверяет и распаковывает в root.
    code_only=True -- только исходники для SAST; False -- весь архив для
    деплоя по манифесту. Возвращает разобранный manifest.json."""
    from app.control_client import _client
    response = _client.get(f"/mcp-artifacts/{c['artifact_id']}/content")
    response.raise_for_status()
    return extract_bundle_archive(response.content, root, code_only)


def extract_bundle_archive(content: bytes, root: Path, code_only: bool):
    """Validate metadata before selecting files, in both SAST and runtime modes."""
    import io
    import zipfile

    if len(content) > 50 * 1024 * 1024:
        raise ValueError("MCPB превышает 50 МБ")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ValueError("Файл не является корректным MCPB/ZIP-архивом") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > 5000 or sum(i.file_size for i in infos) > 250 * 1024 * 1024:
            raise ValueError("Превышен лимит распаковки MCPB")
        # Check every entry, including files the SAST filter would skip,
        # before writing anything into the extraction directory.
        for info in infos:
            path = Path(info.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in info.filename or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Небезопасный путь MCPB")

        # manifest.json is metadata, not a source file. Read it independently
        # of code_only, exactly as the upload API does.
        try:
            manifest_info = archive.getinfo("manifest.json")
        except KeyError as exc:
            raise ValueError("В корне MCPB отсутствует manifest.json") from exc
        if manifest_info.file_size > 1024 * 1024:
            raise ValueError("manifest.json превышает ограничение 1 МиБ")
        try:
            manifest = json.loads(archive.read(manifest_info))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("manifest.json должен содержать корректный JSON") from exc
        if not isinstance(manifest, dict):
            raise ValueError("manifest.json должен содержать JSON-объект")

        for info in infos:
            path = Path(info.filename)
            if info.is_dir():
                continue
            if code_only and path.suffix not in {".py", ".js", ".ts", ".tsx", ".jsx"}:
                continue
            dest = root / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(archive.read(info))
    return manifest


async def bundle_inspect(c):
    """Деплой MCPB по манифесту и снимок каталога tools/list по stdio --
    источник для сканеров каталога (MCPRadar, Cisco, Snyk)."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="mcp-bundle-") as tmp:
        root = Path(tmp) / "bundle"
        root.mkdir()
        manifest = bundle_extract(c, root, code_only=False)
        async with stdio_session_for_bundle(root, manifest, c.get("user_config") or {}) as session:
            tools = await list_tools(session)
            return {"tools": tools}


async def dynamic(c):
    async with session_for(c) as session:
        return await run_dynamic(session, c)


def stdio_command(root: Path, manifest: dict) -> StdioServerParameters:
    """Команда запуска сервера из MCPB по манифесту: mcp_config.command
    приоритетнее, иначе entry_point + server.type (python|node)."""
    server = manifest.get("server") or {}
    mcp_config = server.get("mcp_config") or {}
    entry_point = server.get("entry_point")
    if mcp_config.get("command"):
        command = str(mcp_config["command"])
        args = [str(a) for a in (mcp_config.get("args") or [])]
    elif server.get("type") == "python" and entry_point:
        command, args = "python", [entry_point]
    elif server.get("type") == "node" and entry_point:
        command, args = "node", [entry_point]
    else:
        raise ValueError("Манифест MCPB не описывает запуск: нужен server.type (python|node) + entry_point или server.mcp_config.command")
    if not (root / (args[0] if args else "")).exists() and entry_point and not (root / entry_point).exists():
        raise ValueError(f"entry_point {entry_point} отсутствует в архиве")
    # Секреты окружения: манифест + user_config поверх минимального базового
    # окружения (полный process.env сервера не передаём).
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(root),
        "PYTHONUNBUFFERED": "1",
        **(mcp_config.get("env") or {}),
    }
    return StdioServerParameters(command=command, args=args, env=env, cwd=str(root))


async def deploy_and_check(root: Path, manifest: dict) -> None:
    """Установка зависимостей бандла по его типу до запуска сервера."""
    server_type = (manifest.get("server") or {}).get("type")
    from app.process import execute

    if server_type == "python" and (root / "requirements.txt").exists():
        deps = root / ".bundle-deps"
        deps.mkdir(exist_ok=True)
        rc, _, stderr = execute(
            ["pip", "install", "--no-cache-dir", "--target", str(deps), "-r", "requirements.txt"],
            cwd=root, timeout=180,
            env={"PYTHONPATH": str(deps)},
        )
        if rc:
            raise ValueError("pip install зависимостей MCPB завершился с ошибкой: " + stderr[-400:])
        os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, [str(deps), os.environ.get("PYTHONPATH")]))

    if server_type == "node" and (root / "package.json").exists():
        rc, _, stderr = execute(["npm", "install", "--omit=dev", "--no-audit", "--no-fund", "--loglevel=error"], cwd=root, timeout=180)
        if rc:
            raise ValueError("npm install зависимостей MCPB завершился с ошибкой: " + stderr[-400:])


@asynccontextmanager
async def stdio_session_for_bundle(root: Path, manifest: dict, user_config: dict):
    """Деплой MCPB: установка зависимостей, запуск сервера из манифеста и
    MCP-сеанс по stdio (внутри контейнера сканера)."""
    await deploy_and_check(root, manifest)
    params = stdio_command(root, manifest)
    # user_config из актива передаётся переменными окружения запуска.
    params = StdioServerParameters(
        command=params.command,
        args=params.args,
        cwd=params.cwd,
        env={**{k: v for k, v in (params.env or {}).items()}, **{str(k): str(v) for k, v in (user_config or {}).items() if isinstance(v, (str, int, float, bool))}},
    )
    async with stdio_client(params) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            yield session


async def dynamic(c):
    async with session_for(c) as session:
        return await run_dynamic(session, c)


async def run_dynamic(session, c):
    first = await list_tools(session)
    names = {t["name"] for t in first}
    checks = [dict(name="initialize + tools/list", status="passed", evidence=f"Получено инструментов: {len(first)}")]
    findings = []
    for i, probe in enumerate(c.get("probes", [])):
        if not c.get("allow_tool_calls"):
            raise ValueError("Пробные вызовы не подтверждены")
        if probe["tool"] not in names:
            raise ValueError("Проба ссылается на несуществующий инструмент")
        result = await asyncio.wait_for(session.call_tool(probe["tool"], probe["arguments"]), timeout=20)
        data = result.model_dump(mode="json", by_alias=True, exclude_none=True)
        text = json.dumps(data, ensure_ascii=False)
        expected = probe.get("expect_error", False)
        passed = bool(result.isError) == expected
        if "contains" in probe:
            passed = passed and probe["contains"] in text
        if "forbidden" in probe:
            passed = passed and probe["forbidden"] not in text
        checks.append(dict(name=f"Вызов {i+1}: {probe['tool']}", status="passed" if passed else "failed", evidence=text[:4000]))
        if not passed:
            findings.append(dict(rule_id="mcp.dynamic.probe-expectation", severity="medium", title="Ответ инструмента не соответствует проверке", target=probe["tool"], evidence=text[:4000], recommendation="Проверьте контракт инструмента и валидность заданного теста.", category="dynamic"))
    second = await list_tools(session)
    fingerprint = lambda x: hashlib.sha256(json.dumps(x, sort_keys=True).encode()).hexdigest()
    stable = fingerprint(first) == fingerprint(second)
    checks.append(dict(name="Стабильность каталога в сессии", status="passed" if stable else "failed", evidence=f"{fingerprint(first)} → {fingerprint(second)}"))
    if not stable:
        findings.append(dict(rule_id="mcp.dynamic.catalog-drift", severity="medium", title="Каталог изменился в пределах сессии", target=c.get("server_url") or "bundle", evidence="Различаются имена, описания или схемы tools/list. Изменение может быть легитимным.", recommendation="Сравните снимки и проверьте доверие к обновлениям инструментов.", category="dynamic"))
    return dict(findings=findings, checks=checks, tools_checked=len(first), coverage="Действительный MCP-сеанс и только явно заданные calls. Не проверяет исполнение агентом промпт-инъекций или все классы уязвимостей.")
