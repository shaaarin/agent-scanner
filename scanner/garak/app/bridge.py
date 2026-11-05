"""Bridge-эндпоинт OpenAI chat/completions поверх тестируемого агента.

Red-team движки (garak, PyRIT) умеют целиться в OpenAI-совместимый API, а
агент поднят по `api_config`/`langgraph` из AgentConfig. Bridge принимает их
запросы, достаёт последнее пользовательское сообщение и пересылает его агенту
через `target.send_message`, заворачивая ответ в формат chat.completion.
Код не выносится в общий модуль по соглашению репозитория.
"""
import threading
import time
import uuid

from app.target import send_message


class AgentBridge:
    """Держит конфиг агента активного скана и счётчики запросов."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._agent_config: dict | None = None
        self.requests = 0
        self.errors = 0

    def activate(self, agent_config: dict) -> None:
        with self._lock:
            self._agent_config = agent_config
            self.requests = 0
            self.errors = 0

    def deactivate(self) -> None:
        with self._lock:
            self._agent_config = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._agent_config is not None

    def stats(self) -> dict:
        with self._lock:
            return {"requests": self.requests, "errors": self.errors}

    @staticmethod
    def _last_user_text(messages: list) -> str:
        """Последнее пользовательское сообщение; multimodal-части склеиваются."""
        for message in reversed(messages or []):
            if message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(str(part.get("text") or ""))
                return "\n".join(parts)
            return str(content or "")
        raise ValueError("в запросе нет пользовательского сообщения")

    def chat(self, messages: list) -> str:
        """Отправить последнее пользовательское сообщение агенту, вернуть ответ."""
        with self._lock:
            agent_config = self._agent_config
        if agent_config is None:
            raise RuntimeError("bridge не активирован (агент не запущен)")
        text = self._last_user_text(messages)
        with self._lock:
            self.requests += 1
        try:
            reply = send_message(agent_config, text)
        except Exception:
            with self._lock:
                self.errors += 1
            raise
        return reply


def completion_response(model: str, content: str) -> dict:
    """Ответ в формате OpenAI chat.completion."""
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
