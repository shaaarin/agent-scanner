"""Подстановка косвенной инъекции в тело исходящего запроса агента к LLM.

Инструмент выполняется внутри агента, поэтому его результат прокси видит не
как ответ, а как сообщение `role: "tool"` в следующем запросе агента к
`chat/completions`. Сюда и дописывается payload -- для модели это выглядит
так, будто текст вернул сам инструмент.

Прокси применяет директиву «тупо» и без состояния: оценку и выбор payload
делает scanner-indirect. Агент каждый ход присылает всю историю заново, а
исходный результат инструмента у него чистый, поэтому для режима append
повторное применение на каждом запросе прогона даёт один и тот же augmented
результат.
"""
from typing import Any, Optional

ANY_TOOL = "*"


def _augment(content: Any, payload: str, mode: str) -> Any:
    """Дописать payload в content сообщения tool. content бывает строкой или
    списком частей (OpenAI допускает оба)."""
    if isinstance(content, list):
        part = {"type": "text", "text": payload}
        return [part, *content] if mode == "prepend" else [*content, part]
    text = "" if content is None else str(content)
    if mode == "replace":
        return payload
    if mode == "prepend":
        return f"{payload}\n\n{text}"
    return f"{text}\n\n{payload}"  # append (по умолчанию) / wrap


def apply(body: dict, directive: dict) -> tuple[dict, bool, Optional[str]]:
    """Вернуть (тело, применено ли, в какой инструмент). Тело меняется на
    месте; если подложить некуда (нужного вызова инструмента в истории нет) --
    (body, False, None)."""
    target = directive.get("target_tool") or ANY_TOOL
    occurrence = int(directive.get("occurrence") or 1)
    mode = directive.get("mode") or "append"
    payload = directive.get("payload_text") or ""
    messages = body.get("messages")
    if not payload or not isinstance(messages, list):
        return body, False, None

    # tool_call_id -> имя инструмента (из tool_calls сообщений assistant):
    # сопоставить сообщение tool с его инструментом иначе нельзя.
    id_to_name: dict[str, str] = {}
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        for call in msg.get("tool_calls") or []:
            call_id = call.get("id")
            name = (call.get("function") or {}).get("name")
            if call_id and name:
                id_to_name[call_id] = name

    seen = 0
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "tool":
            continue
        name = id_to_name.get(msg.get("tool_call_id")) or msg.get("name") or ""
        if target != ANY_TOOL and name != target:
            continue
        seen += 1
        if seen == occurrence:
            msg["content"] = _augment(msg.get("content"), payload, mode)
            return body, True, (name or target)
    return body, False, None


SYSTEM_ROLE = "system"


def apply_system(body: dict, directive: dict) -> tuple[dict, bool, Optional[str]]:
    """Вставить метку `canary` в системное сообщение (скан system_prompt_leak).
    Если системного сообщения нет -- добавить его в начало. Метка оформляется
    так, будто это часть инструкций: если агент выдаст свой системный промпт,
    метка «уедет» вместе с ним, и утечку видно по её появлению в ответе."""
    canary = directive.get("canary") or ""
    mode = directive.get("mode") or "append"
    messages = body.get("messages")
    if not canary or not isinstance(messages, list):
        return body, False, None
    sentinel = f"[sysnote:{canary}]"
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == SYSTEM_ROLE:
            msg["content"] = _augment(msg.get("content"), sentinel, mode)
            return body, True, SYSTEM_ROLE
    messages.insert(0, {"role": SYSTEM_ROLE, "content": sentinel})
    return body, True, SYSTEM_ROLE
