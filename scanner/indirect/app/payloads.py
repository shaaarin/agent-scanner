"""Загрузка тест-фикстур payload'ов и подстановка меток прогона."""
import uuid
from pathlib import Path

import yaml

_PAYLOADS_FILE = Path(__file__).parent / "payloads" / "payloads.yaml"


def load_payloads() -> list[dict]:
    """Все payload'ы из YAML. Поля: name, family, mode, template."""
    with _PAYLOADS_FILE.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or []
    return [p for p in data if p.get("name") and p.get("template")]


def new_canary() -> str:
    """Уникальная метка прогона. Случайная строка, которую нельзя встретить
    в ответе агента случайно -- поэтому её появление однозначно."""
    return f"CANARY-{uuid.uuid4().hex[:12].upper()}"


def render(template: str, *, canary: str, tool_name: str) -> str:
    return template.replace("{{canary}}", canary).replace("{{tool_name}}", tool_name).strip()
