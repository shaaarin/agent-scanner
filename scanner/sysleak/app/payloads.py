"""Датасет атакующих промптов, подключение внешних наборов и варианты.

Источники промптов:

1. встроенный `payloads/payloads.yaml` (едет в образе);
2. любой `*.yaml`/`*.yml` из каталога `EXTRA_PAYLOADS_DIR` -- так подключается
   свой или сторонний набор **без пересборки образа** (каталог монтируется
   read-only, как библиотека знаний).

Поверх базовых текстов работают мутаторы (`app/mutators.py`): один промпт ×
выбранные мутаторы = несколько вариантов в разных обёртках. Отсюда покрытие:
15 базовых промптов × 10 мутаторов = 150 вариантов, без обращений к LLM и без
потери воспроизводимости.
"""
import os
import uuid
from pathlib import Path

import yaml

from app import mutators

_BUNDLED_FILE = Path(__file__).parent / "payloads" / "payloads.yaml"
EXTRA_PAYLOADS_DIR = os.environ.get("EXTRA_PAYLOADS_DIR", "/payloads")


def _read_file(path: Path) -> list[dict]:
    try:
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or []
    except (OSError, yaml.YAMLError) as exc:
        print(f"[payloads] не удалось прочитать {path}: {exc}")
        return []
    if not isinstance(data, list):
        print(f"[payloads] {path}: ожидался список промптов")
        return []
    return [item for item in data if isinstance(item, dict) and item.get("name") and item.get("prompt")]


def load_payloads() -> list[dict]:
    """Базовые промпты: встроенные плюс внешние. Поля: name, family, prompt.
    Одинаковые имена не дублируются -- внешний набор переопределяет
    встроенный, так что штатный промпт можно заменить своим."""
    by_name: dict[str, dict] = {}
    for payload in _read_file(_BUNDLED_FILE):
        by_name[payload["name"]] = {**payload, "source": "bundled"}

    extra_dir = Path(EXTRA_PAYLOADS_DIR)
    if extra_dir.is_dir():
        for path in sorted(extra_dir.glob("*.y*ml")):
            for payload in _read_file(path):
                by_name[payload["name"]] = {**payload, "source": path.name}
    return list(by_name.values())


def new_canary() -> str:
    """Уникальная метка прогона, которую прокси вставит в системное сообщение.
    Случайная строка -- в ответе агента она не может появиться случайно."""
    return f"SYSCANARY-{uuid.uuid4().hex[:12].upper()}"


def build_variants(payloads: list[dict], mutator_names: list[str]) -> list[dict]:
    """Декартово произведение «промпт × мутатор». Текст собирается сразу:
    метки в промпте нет (её вставляет прокси в системное сообщение), поэтому
    от прогона он не зависит."""
    names = [name for name in (mutator_names or mutators.DEFAULT_MUTATORS)]
    unknown = [name for name in names if name not in mutators.MUTATORS]
    if unknown:
        raise ValueError(f"неизвестные мутаторы: {', '.join(unknown)}")

    variants: list[dict] = []
    for payload in payloads:
        for mutator in names:
            variants.append(
                {
                    "name": payload["name"] if mutator == "none" else f"{payload['name']}/{mutator}",
                    "base_name": payload["name"],
                    "family": payload.get("family"),
                    "mutator": mutator,
                    "prompt": mutators.apply(mutator, payload["prompt"].strip(), ""),
                }
            )
    return variants
