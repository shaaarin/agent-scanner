import asyncio
import hashlib
import ipaddress
import json
import socket
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
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


async def dynamic(c):
    async with session_for(c) as session:
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
            findings.append(dict(rule_id="mcp.dynamic.catalog-drift", severity="medium", title="Каталог изменился в пределах сессии", target=c["server_url"], evidence="Различаются имена, описания или схемы tools/list. Изменение может быть легитимным.", recommendation="Сравните снимки и проверьте доверие к обновлениям инструментов.", category="dynamic"))
        return dict(findings=findings, checks=checks, tools_checked=len(first), coverage="Действительный MCP-сеанс и только явно заданные calls. Не проверяет исполнение агентом промпт-инъекций или все классы уязвимостей.")
