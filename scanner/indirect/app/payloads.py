"""Датасет payload'ов, подключение внешних наборов и разворачивание вариантов.

Источники payload'ов:

1. встроенный `payloads/payloads.yaml` (едет в образе);
2. любой `*.yaml`/`*.yml` из каталога `EXTRA_PAYLOADS_DIR` -- так подключается
   свой или сторонний набор **без пересборки образа** (каталог монтируется
   read-only, как библиотека знаний).

Поверх базовых текстов работают мутаторы (`app/mutators.py`): один payload ×
выбранные мутаторы = несколько вариантов той же инъекции в разных обёртках.
Отсюда и берётся покрытие: 14 базовых payload'ов × 10 мутаторов = 140
вариантов, и это без обращений к LLM и без потери воспроизводимости.
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
        print(f"[payloads] {path}: ожидался список payload'ов")
        return []
    return [item for item in data if isinstance(item, dict) and item.get("name") and item.get("template")]


def load_payloads() -> list[dict]:
    """Базовые payload'ы: встроенные плюс внешние. Поля: name, family, mode,
    template. Одинаковые имена не дублируются -- внешний набор переопределяет
    встроенный, так что штатный payload можно заменить своим."""
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
    """Уникальная метка прогона. Случайная строка, которую нельзя встретить
    в ответе агента случайно -- поэтому её появление однозначно."""
    return f"CANARY-{uuid.uuid4().hex[:12].upper()}"


def render(template: str, *, canary: str, tool_name: str) -> str:
    return template.replace("{{canary}}", canary).replace("{{tool_name}}", tool_name).strip()


def build_variants(payloads: list[dict], mutator_names: list[str]) -> list[dict]:
    """Декартово произведение «payload × мутатор».

    Сам текст тут не собирается: метка уникальна для каждого прогона, поэтому
    `render` + `mutators.apply` вызываются в раннере. Вариант несёт только
    ссылку на базовый payload и имя мутатора, а `name` -- как он будет виден
    в журнале и результатах.
    """
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
                    "mode": payload.get("mode") or "append",
                    "template": payload["template"],
                    "mutator": mutator,
                }
            )
    return variants


def build_text(variant: dict, *, canary: str, tool_name: str) -> str:
    """Готовый текст инъекции для прогона: подстановка метки, затем мутатор."""
    text = render(variant["template"], canary=canary, tool_name=tool_name)
    return mutators.apply(variant["mutator"], text, canary)
