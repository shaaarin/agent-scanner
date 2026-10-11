"""Кастомная цель PyRIT: переводит сообщения атак в HTTP-вызовы тестируемого
агента. В отличие от DeepTeam-коллбэка (свежий диалог на каждое сообщение),
здесь разговор один на атаку: LangGraph-нить или `{{session_id}}` живут всю
атаку, поэтому многораундовые стратегии (RedTeaming, Crescendo) ведут с
агентом настоящий диалог с контекстом.

PyRIT v1.x: subclass `PromptTarget` с override `_send_prompt_to_target_async`;
`send_prompt_async` финален и сам ведёт память/валидацию. Ответ собирается
хелпером `construct_response_from_request` -- метаданные (conversation_id,
цель) наследуются от запроса.

Два режима (`AgentConfig.interaction_mode`) и контракт `api_config` -- те же,
что у scanner-deepteam (`scanner/deepteam/app/target.py`):

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

  Плейсхолдеры: {{message}} -- сообщение атаки; {{session_id}} -- UUID,
  один на разговор атаки (для API, которым нужен id диалога).
"""
import asyncio
import json
import re
import uuid
from typing import Any, Callable, Optional
from urllib.parse import quote

import httpx

from pyrit.models import Message, construct_response_from_request
from pyrit.prompt_target import PromptTarget
from pyrit.prompt_target.common.target_capabilities import TargetCapabilities
from pyrit.prompt_target.common.target_configuration import TargetConfiguration

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
    это ошибка атаки, а не «весь ответ как текст»: иначе судья оценивает
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


class AgentPromptTarget(PromptTarget):
    """Атакуемый агент как цель PyRIT: полный диалог в нормализованной
    истории, но наружу уходит только последнее сообщение пользователя --
    контекст агент ведёт сам (нить LangGraph или свой session_id)."""

    # Чат-цель для многораундовых атак: историю ведём (на стороне агента),
    # системный промпт через HTTP API не задаём.
    _DEFAULT_CONFIGURATION = TargetConfiguration(
        capabilities=TargetCapabilities(
            supports_multi_turn=True,
            supports_editable_history=True,
            supports_system_prompt=False,
        )
    )

    def __init__(self, *, agent_config: dict, on_log: Optional[Callable[[str, str], None]] = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._agent_config = agent_config
        self._on_log = on_log or (lambda level, message: None)
        self._mode = agent_config.get("interaction_mode")
        # Ресурсы диалогов: conversation_id атаки -> нить LangGraph / session_id.
        self._threads: dict[str, str] = {}
        self._sessions: dict[str, str] = {}
        if self._mode == "langgraph":
            langgraph_config = agent_config.get("langgraph_config") or {}
            if not langgraph_config.get("base_url"):
                raise RuntimeError(
                    "у агента не задан langgraph_config.base_url -- укажите api_port в конфиге агента, "
                    "чтобы launcher автоматически пробросил адрес"
                )
        elif self._mode == "api":
            api_config = agent_config.get("api_config") or {}
            if not api_config.get("url"):
                raise RuntimeError("у агента не задан api_config.url -- укажите api_port, чтобы launcher пробросил адрес")
            try:
                render_request(api_config, "проверка шаблона")
            except ValueError as exc:
                raise RuntimeError(f"некорректная настройка REST API агента: {exc}") from exc
        else:
            raise RuntimeError(f"interaction_mode={self._mode!r} не поддерживает интерактивное сканирование")

    async def _send_prompt_to_target_async(self, *, normalized_conversation: list[Message]) -> list[Message]:
        current = normalized_conversation[-1]
        piece = current.message_pieces[0]
        message = piece.converted_value or piece.original_value
        conversation_id = piece.conversation_id
        if not message:
            raise RuntimeError("пустое сообщение атаки")
        reply = await asyncio.to_thread(self._send_sync, conversation_id, str(message))
        return [construct_response_from_request(request=piece, response_text_pieces=[reply])]

    def _send_sync(self, conversation_id: str, message: str) -> str:
        if self._mode == "langgraph":
            return self._send_via_langgraph(conversation_id, message)
        return self._send_via_api(conversation_id, message)

    def _send_via_api(self, conversation_id: str, message: str) -> str:
        api_config = self._agent_config.get("api_config") or {}
        # Один session_id на разговор атаки: у API с сессиями многотановая
        # атака видна как один диалог.
        session_id = self._sessions.setdefault(conversation_id, str(uuid.uuid4()))
        with httpx.Client(timeout=120.0) as client:
            resp = client.request(**render_request(api_config, message, session_id))
            resp.raise_for_status()
            return extract_reply(resp, api_config.get("response_field", _DEFAULT_RESPONSE_FIELD))

    def _send_via_langgraph(self, conversation_id: str, message: str) -> str:
        langgraph_config = self._agent_config.get("langgraph_config") or {}
        base_url = langgraph_config["base_url"].rstrip("/")
        assistant_id = langgraph_config.get("assistant_id", "agent")
        headers = {}
        if langgraph_config.get("api_key"):
            headers["X-Api-Key"] = langgraph_config["api_key"]

        with httpx.Client(base_url=base_url, headers=headers, timeout=120.0) as client:
            thread_id = self._threads.get(conversation_id)
            if not thread_id:
                thread = client.post("/threads", json={})
                thread.raise_for_status()
                thread_id = thread.json()["thread_id"]
                self._threads[conversation_id] = thread_id
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
            # атаки, а не пустой ответ агента, иначе судья оценит её как
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
