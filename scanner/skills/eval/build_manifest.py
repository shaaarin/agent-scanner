"""Генерирует manifest.yaml по содержимому corpus/.

Метки для фикстур Cisco берутся из их _expected.json (package_label), остальное — из
таблицы ниже. Запуск: python build_manifest.py (манифест коммитится; тест проверяет, что он
совпадает с диском).
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from corpus import CORPUS_DIR, EVAL_DIR, MANIFEST, find_skill_dirs

CISCO_LABELS = {"malicious": "malicious", "benign": "benign", "contextual_risk": "contextual"}

# (каталог относительно corpus/) -> (label, technique, source)
EXPLICIT = {
    "cisco-test/malicious/ascii-smuggling": ("malicious", "unicode-steganography", "cisco/evals/test_skills"),
    "cisco-test/malicious/exfiltrator": ("malicious", "data-exfiltration", "cisco/evals/test_skills"),
    "cisco-test/malicious/flowise-cve-2025-59528": ("malicious", "command-injection", "cisco/evals/test_skills"),
    "cisco-test/malicious/mcp-atlassian-cve-2026-27825": ("malicious", "path-traversal", "cisco/evals/test_skills"),
    "cisco-test/malicious/mcpwn-cve-2026-33032": ("malicious", "mcp-abuse", "cisco/evals/test_skills"),
    "cisco-test/malicious/prompt-injection": ("malicious", "prompt-injection", "cisco/evals/test_skills"),
    "cisco-test/safe/atr-benign-control": ("benign", "legit-fixture", "cisco/evals/test_skills"),
    "cisco-test/safe/simple-formatter": ("benign", "legit-fixture", "cisco/evals/test_skills"),
    "skillspector/malicious_skill": ("malicious", "mixed", "skillspector/tests/fixtures"),
    "skillspector/safe_skill": ("benign", "legit-fixture", "skillspector/tests/fixtures"),
    "skillspector/tp4_markdown_fenced_code": ("benign", "fenced-code-false-positive", "skillspector/tests/fixtures"),
    "skillspector/pe3_bare_keyring": ("contextual", "keyring-access", "skillspector/tests/fixtures"),
    "marker/hooks-command": ("malicious", "claude-code-hooks", "own marker fixture"),
    "marker/shell-persistence": ("malicious", "shell-persistence", "own marker fixture"),
    "marker/bang-injection": ("malicious", "claude-code-bang-injection", "own marker fixture"),
    "marker/bang-network": ("malicious", "claude-code-bang-injection", "own marker fixture"),
    "marker/benign-plain": ("benign", "legit-fixture", "own marker fixture"),
}


def build() -> dict:
    cases = []
    for d in find_skill_dirs(CORPUS_DIR):
        rel = d.relative_to(CORPUS_DIR).as_posix()
        if rel.startswith("cisco/"):
            expected = json.loads((d / "_expected.json").read_text(encoding="utf-8"))
            label = CISCO_LABELS[expected["package_label"]]
            technique = rel.split("/")[1]
            source = "cisco/evals/skills"
        elif rel in EXPLICIT:
            label, technique, source = EXPLICIT[rel]
        else:
            raise SystemExit(f"нет описания для {rel}: добавьте в EXPLICIT")
        cases.append(
            {"id": rel, "path": f"corpus/{rel}", "label": label, "technique": technique, "source": source}
        )
    return {"cases": cases}


def main() -> None:
    MANIFEST.write_text(
        "# Сгенерировано build_manifest.py — не править руками.\n"
        + yaml.safe_dump(build(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"{len(build()['cases'])} кейсов -> {MANIFEST.relative_to(EVAL_DIR)}")


if __name__ == "__main__":
    main()
