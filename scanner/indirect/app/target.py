"""Отправка одной легитимной задачи тестируемому агенту и получение его
финального ответа. Поддерживает те же два режима, что scanner-deepteam
(`langgraph` и произвольный `api`), с тем же контрактом `api_config`.
Код не выносится в общий модуль по соглашению репозитория."""
import json
import re
import uuid
from typing import Any, Optional
from urllib.parse import quote

import httpx

_DEFAULT_REQUEST_BODY_TEMPLATE = {"message": "{{message}}"}
_DEFAULT_RESPONSE_FIELD = "reply"
API_METHODS = ("POST", "GET", "PUT", "PATCH")
BODY_FORMATS = ("json", "form", "text")

_PLACEHOLDER_RE = re.compile(r"\{\{(message|session_id)\}\}")


def _fill(text: str, values: dict[str, str], *, url_encode: bool = False) -> str:
    def repl(match: re.Match) -> str:
        value = values[match.group(1)]
        return quote(value, safe="") if url_encode else value

    return _PLACEHOLDER_RE.sub(repl, text)


def _substitute(node: Any, values: dict[str, str]) -> Any:
    if isinstance(node, str):
        return _fill(node, values)
    if isinstance(node, dict):
        return {k: _substitute(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute(v, values) for v in node]
    return node


def render_request(api_config: dict, message: str, session_id: Optional[str] = None) -> dict:
    values = {"message": message, "session_id": session_id or str(uuid.uuid4())}
    method = str(api_config.get("method") or "POST").upper()
    if method not in API_METHODS:
        raise ValueError(f"неподдерживаемый метод {method}")
    body_format = str(api_config.get("body_format") or "json").lower()
    if body_format not in BODY_FORMATS:
        raise ValueError(f"неподдерживаемый формат тела {body_format}")

    template = api_config.get("request_body_template", _DEFAULT_REQUEST_BODY_TEMPLATE)
    if body_format in ("json", "form") and isinstance(template, str):
        try:
            template = json.loads(template)
        except json.JSONDecodeError as exc:
            raise ValueError(f"шаблон тела не является JSON: {exc}") from exc

    request: dict[str, Any] = {
        "method": method,
        "url": _fill(str(api_config["url"]), values, url_encode=True),
        "headers": {str(k): _fill(str(v), values) for k, v in (api_config.get("headers") or {}).items()},
    }
    if body_format == "text":
        request["content"] = _fill(str(template or ""), values).encode()
        request["headers"].setdefault("Content-Type", "text/plain; charset=utf-8")
    elif method == "GET":
        if template:
            request["params"] = _substitute(template, values)
    elif body_format == "form":
        request["data"] = {str(k): str(v) for k, v in _substitute(template or {}, values).items()}
    else:
        request["json"] = _substitute(template, values)
    return request


def _extract(data: Any, path: str) -> Any:
    current = data
    for segment in path.split("."):
        if isinstance(current, list):
            try:
                current = current[int(segment)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"в списке длиной {len(current)} нет элемента {segment!r}") from exc
        elif isinstance(current, dict):
            if segment not in current:
                keys = ", ".join(list(current)[:10]) or "нет полей"
                raise KeyError(f"нет поля {segment!r} (есть: {keys})")
            current = current[segment]
        else:
            raise KeyError(f"нельзя взять {segment!r} у значения типа {type(current).__name__}")
    return current


def extract_reply(resp: httpx.Response, response_field: Optional[str]) -> str:
    field = (response_field or "").strip()
    if not field:
        return resp.text
    try:
        data = resp.json()
    except ValueError:
        return resp.text
    try:
        value = _extract(data, field)
    except KeyError as exc:
        raise RuntimeError(f"не удалось взять {field!r} из ответа агента: {exc.args[0]}") from exc
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _send_via_api(api_config: dict, message: str) -> str:
    with httpx.Client(timeout=180.0) as client:
        resp = client.request(**render_request(api_config, message))
        resp.raise_for_status()
        return extract_reply(resp, api_config.get("response_field", _DEFAULT_RESPONSE_FIELD))


def _send_via_langgraph(langgraph_config: dict, message: str) -> str:
    base_url = langgraph_config["base_url"].rstrip("/")
    assistant_id = langgraph_config.get("assistant_id", "agent")
    headers = {}
    if langgraph_config.get("api_key"):
        headers["X-Api-Key"] = langgraph_config["api_key"]

    with httpx.Client(base_url=base_url, headers=headers, timeout=180.0) as client:
        thread = client.post("/threads", json={})
        thread.raise_for_status()
        thread_id = thread.json()["thread_id"]
        try:
            resp = client.post(
                f"/threads/{thread_id}/runs/wait",
                json={
                    "assistant_id": assistant_id,
                    "input": {"messages": [{"role": "user", "content": message}]},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and data.get("__error__"):
                err = data["__error__"]
                detail = f"{err.get('error')}: {err.get('message')}" if isinstance(err, dict) else str(err)
                raise RuntimeError(f"агент вернул ошибку: {detail}")
            messages = (data.get("messages") if isinstance(data, dict) else None) or []
            for msg in reversed(messages):
                if msg.get("type") in ("ai", "assistant") or msg.get("role") in ("assistant", "ai"):
                    return str(msg.get("content", ""))
            return ""
        finally:
            try:
                client.delete(f"/threads/{thread_id}")
            except httpx.HTTPError:
                pass


def send_message(agent_config: dict, message: str) -> str:
    """Отправить агенту одно сообщение, вернуть его финальный ответ."""
    mode = agent_config.get("interaction_mode")
    if mode == "langgraph":
        langgraph_config = agent_config.get("langgraph_config") or {}
        if not langgraph_config.get("base_url"):
            raise RuntimeError("у агента не задан langgraph_config.base_url (нужен api_port)")
        return _send_via_langgraph(langgraph_config, message)
    if mode == "api":
        api_config = agent_config.get("api_config") or {}
        if not api_config.get("url"):
            raise RuntimeError("у агента не задан api_config.url (нужен api_port)")
        return _send_via_api(api_config, message)
    raise RuntimeError(f"interaction_mode={mode!r} не поддерживает интерактивное сканирование")
