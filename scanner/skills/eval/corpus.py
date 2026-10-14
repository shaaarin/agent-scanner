"""Корпус для сравнения движков: манифест и поиск скиллов на диске."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

EVAL_DIR = Path(__file__).resolve().parent
CORPUS_DIR = EVAL_DIR / "corpus"
MANIFEST = EVAL_DIR / "manifest.yaml"
EXTERNAL_DIR = EVAL_DIR / ".external"
EXTERNAL_ANTHROPIC = EXTERNAL_DIR / "anthropics-skills"
# Ссылка на внешний корпус зафиксирована коммитом; сами файлы в репозиторий не копируем
# (часть навыков anthropics/skills — source-available, не Apache-2.0).
EXTERNAL_ANTHROPIC_COMMIT = "dbd4588f9e1033efb41dad4bef2f7947c8993d44"

LABELS = {"malicious", "benign", "contextual"}


@dataclass(frozen=True)
class Case:
    id: str
    path: Path          # каталог со SKILL.md
    label: str          # malicious | benign | contextual
    technique: str
    source: str


def load_manifest(manifest: Path = MANIFEST, base: Path = EVAL_DIR) -> list[Case]:
    raw = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    cases = []
    for item in raw.get("cases", []):
        if item["label"] not in LABELS:
            raise ValueError(f"{item['id']}: неизвестная метка {item['label']!r}")
        cases.append(Case(item["id"], base / item["path"], item["label"], item["technique"], item["source"]))
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("повторяющиеся id в манифесте")
    return cases


def external_cases(root: Path = EXTERNAL_ANTHROPIC) -> list[Case]:
    """Легитимные негативы из anthropics/skills (если репозиторий склонирован fetch_external.sh)."""
    skills = root / "skills"
    if not skills.is_dir():
        return []
    return [
        Case(f"anthropic/{d.name}", d, "benign", "legit-anthropic", "anthropics/skills")
        for d in sorted(skills.iterdir())
        if (d / "SKILL.md").is_file()
    ]


def find_skill_dirs(root: Path) -> list[Path]:
    """Все каталоги, где лежит SKILL.md (имя файла — регистронезависимо не ищем: спецификация требует SKILL.md)."""
    return sorted(p.parent for p in root.rglob("SKILL.md"))
