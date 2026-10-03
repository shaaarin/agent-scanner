"""The DeepTeam `model_callback`: bridges DeepTeam's synchronous callback
into the tested agent's own external API. DeepTeam passes one attack payload
at a time; each payload becomes a fresh conversation with the agent so
attacks don't leak context into each other.

Два режима (`AgentConfig.interaction_mode`):

- `langgraph` -- LangGraph API (threads + runs/wait), см. `_send_via_langgraph`;
- `api` -- произвольный HTTP API, описанный `api_config`:

    url                    -- адрес; плейсхолдеры допустимы в пути и query
                              (подставляются URL-кодированными)
    method                 -- POST (по умолчанию), GET, PUT, PATCH
    headers                -- {имя: значение}, плейсхолдеры допустимы
    body_format            -- json (по умолчанию) | form | text
    request_body_template  -- json: любой JSON, плейсхолдеры в строках;
                              form: объект; text: строка. Для GET объект
                              уходит в query-параметры
    response_field         -- путь к ответу агента в JSON: "reply",
                              "data.0.text", "messages.-1.content"
                              (отрицательный индекс -- с конца). Пусто --
                              весь ответ как текст
    health_path            -- путь для проверки готовности; не задан -- как
                              раньше: путь эндпоинта без "/chat" + "/ok"
                              (или "/", если в пути есть плейсхолдер)

  Плейсхолдеры: {{message}} -- атакующее сообщение; {{session_id}} --
  новый UUID на каждый разговор (для API, которым нужен id диалога).
"""
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
    """Подстановка в один проход: если в тексте атаки окажется строка
    «{{session_id}}», она останется как есть, а не будет заменена."""

    def repl(match: re.Match) -> str:
        value = values[match.group(1)]
        return quote(value, safe="") if url_encode else value

    return _PLACEHOLDER_RE.sub(repl, text)


def _substitute(node: Any, values: dict[str, str]) -> Any:
    """Подстановка в строковые значения JSON-шаблона. Шаблон уже разобран,
    поэтому кавычки и переводы строк в сообщении экранируются при
    сериализации, а не ломают JSON."""
    if isinstance(node, str):
        return _fill(node, values)
    if isinstance(node, dict):
        return {k: _substitute(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute(v, values) for v in node]
    return node


def render_request(api_config: dict, message: str, session_id: str | None = None) -> dict:
    """api_config + сообщение -> аргументы для httpx.Client.request.
    Отдельная функция, чтобы запрос можно было проверить без сети."""
    values = {"message": message, "session_id": session_id or str(uuid.uuid4())}
    method = str(api_config.get("method") or "POST").upper()
    if method not in API_METHODS:
        raise ValueError(f"неподдерживаемый метод {method}, ожидается один из: {', '.join(API_METHODS)}")
    body_format = str(api_config.get("body_format") or "json").lower()
    if body_format not in BODY_FORMATS:
        raise ValueError(f"неподдерживаемый формат тела {body_format}, ожидается один из: {', '.join(BODY_FORMATS)}")

    template = api_config.get("request_body_template", _DEFAULT_REQUEST_BODY_TEMPLATE)
    if body_format in ("json", "form") and isinstance(template, str):
        # шаблон мог быть сохранён строкой с JSON внутри
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


def extract_reply(resp: httpx.Response, response_field: str | None) -> str:
    """Ответ агента из HTTP-ответа. Если поле указано, а его нет --
    это ошибка кейса, а не «весь ответ как текст»: иначе судья оценивает
    служебный JSON вместо ответа агента."""
    field = (response_field or "").strip()
    if not field:
        return resp.text
    try:
        data = resp.json()
    except ValueError:
        # Не JSON (например, text/plain) -- поле взять неоткуда, отдаём текст.
        return resp.text
    try:
        value = _extract(data, field)
    except KeyError as exc:
        raise RuntimeError(f"не удалось взять {field!r} из ответа агента: {exc.args[0]}") from exc
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _send_via_api(api_config: dict, message: str, client: httpx.Client) -> str:
    resp = client.request(**render_request(api_config, message))
    resp.raise_for_status()
    return extract_reply(resp, api_config.get("response_field", _DEFAULT_RESPONSE_FIELD))


def _send_via_langgraph(langgraph_config: dict, message: str) -> str:
    base_url = langgraph_config["base_url"].rstrip("/")
    assistant_id = langgraph_config.get("assistant_id", "agent")
    headers = {}
    if langgraph_config.get("api_key"):
        headers["X-Api-Key"] = langgraph_config["api_key"]

    with httpx.Client(base_url=base_url, headers=headers, timeout=120.0) as client:
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
            # LangGraph отдаёт падение графа (например, RateLimitError от LLM
            # агента) как HTTP 200 с телом {"__error__": {...}}. Это ошибка
            # кейса, а не пустой ответ агента, иначе судья оценит её как
            # «устойчив».
            if isinstance(data, dict) and data.get("__error__"):
                err = data["__error__"]
                detail = f"{err.get('error')}: {err.get('message')}" if isinstance(err, dict) else str(err)
                raise RuntimeError(f"агент вернул ошибку: {detail}")
            messages = (data.get("messages") if isinstance(data, dict) else None) or []
            for msg in reversed(messages):
                # LangGraph emits its own message schema: `type` is
                # "human"/"ai"/"tool" and `role` is often absent.
                if msg.get("type") in ("ai", "assistant") or msg.get("role") in ("assistant", "ai"):
                    return str(msg.get("content", ""))
            return ""
        finally:
            try:
                client.delete(f"/threads/{thread_id}")
            except httpx.HTTPError:
                pass


def build_model_callback(agent_config: dict):
    """Returns a `(input, turns=None) -> str` callback for `deepteam.red_team`.
    `turns` is accepted (so DeepTeam passes multi-turn context) but ignored:
    the UI only seeds single-turn attacks today.
    """
    mode = agent_config.get("interaction_mode")
    if mode == "langgraph":
        langgraph_config = agent_config.get("langgraph_config") or {}
        if not langgraph_config.get("base_url"):
            raise RuntimeError(
                "у агента не задан langgraph_config.base_url -- укажите api_port в конфиге агента, "
                "чтобы launcher автоматически пробросил адрес"
            )

        def callback(input: str, turns: Optional[list] = None) -> str:
            return _send_via_langgraph(langgraph_config, input)

        return callback

    if mode == "api":
        api_config = agent_config.get("api_config") or {}
        if not api_config.get("url"):
            raise RuntimeError("у агента не задан api_config.url -- укажите api_port, чтобы launcher пробросил адрес")
        try:
            render_request(api_config, "проверка шаблона")
        except ValueError as exc:
            raise RuntimeError(f"некорректная настройка REST API агента: {exc}") from exc

        def callback(input: str, turns: Optional[list] = None) -> str:
            with httpx.Client(timeout=120.0) as client:
                return _send_via_api(api_config, input, client)

        return callback

    raise RuntimeError(f"interaction_mode={mode!r} не поддерживает интерактивное сканирование")
