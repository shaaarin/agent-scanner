"""Загрузка атакующих промптов (тест-фикстуры) и генерация меток прогона."""
import uuid
from pathlib import Path

import yaml

_PAYLOADS_FILE = Path(__file__).parent / "payloads" / "payloads.yaml"


def load_payloads() -> list[dict]:
    """Все атакующие промпты из YAML. Поля: name, family, prompt."""
    with _PAYLOADS_FILE.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or []
    return [p for p in data if p.get("name") and p.get("prompt")]


def new_canary() -> str:
    """Уникальная метка прогона, которую прокси вставит в системное сообщение.
    Случайная строка -- в ответе агента она не может появиться случайно."""
    return f"SYSCANARY-{uuid.uuid4().hex[:12].upper()}"
