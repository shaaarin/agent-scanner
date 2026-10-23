"""Мини-проверка frontmatter (D-31): hooks с командами, Bash без ограничений
в allowed-tools, `!`…`` в теле. Образцы инертные (`echo`)."""
from pathlib import Path

import pytest

from app import manifest_check

EVAL_MARKERS = Path(__file__).resolve().parents[1] / "eval" / "corpus" / "marker"


def _skill(tmp_path, text: str, name: str = "SKILL.md") -> Path:
    skill = tmp_path / "skill"
    (skill / name).parent.mkdir(parents=True, exist_ok=True)
    (skill / name).write_text(text)
    return skill


def _rules(run):
    return [(f.rule_id, f.severity, f.file, f.line) for f in run.findings]


HOOKS = """---
name: s
description: d
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "echo one"
        - type: prompt
          prompt: "не команда"
  Stop:
    - hooks:
        - command: "echo two"
---
Тело.
"""


def test_hooks_with_commands(tmp_path):
    run = manifest_check.run(_skill(tmp_path, HOOKS))
    assert run.engine == "manifest" and run.ok and run.version == "1"
    [finding] = run.findings
    assert (finding.rule_id, finding.severity, finding.file, finding.line) == ("MANIFEST_HOOKS_COMMAND", "high", "SKILL.md", 4)
    assert finding.snippet == "echo one; echo two"
    assert finding.category == "command_injection"
    assert "без участия модели" in finding.finding


def test_hooks_without_commands_ignored(tmp_path):
    text = "---\nname: s\nhooks:\n  Stop:\n    - hooks:\n        - type: prompt\n          prompt: x\n---\n"
    assert manifest_check.run(_skill(tmp_path, text)).findings == []


def test_many_hook_commands_shortened(tmp_path):
    commands = "".join(f"        - command: echo {i}\n" for i in range(5))
    text = f"---\nname: s\nhooks:\n  Stop:\n    - hooks:\n{commands}---\n"
    [finding] = manifest_check.run(_skill(tmp_path, text)).findings
    assert finding.snippet == "echo 0; echo 1; echo 2 (и ещё 2)"


def test_recursive_yaml_anchor_does_not_hang(tmp_path):
    text = "---\nname: s\nhooks: &h\n  loop: *h\n  x:\n    command: echo hi\n---\n"
    [finding] = manifest_check.run(_skill(tmp_path, text)).findings
    assert finding.snippet == "echo hi"


@pytest.mark.parametrize(
    "value, flagged",
    [
        ("Bash", True),
        ("Read, Bash", True),
        ("Read Bash Grep", True),
        ("Bash(*)", True),
        ("[Read, Bash]", True),
        ("Bash(git status:*)", False),
        ("Read, Bash(git diff:*), Grep", False),
        ("Read, Grep", False),
        ("'[Bash(npm test:*), Bash(git log:*)]'", False),
    ],
)
def test_allowed_tools(tmp_path, value, flagged):
    run = manifest_check.run(_skill(tmp_path, f"---\nname: s\nallowed-tools: {value}\n---\nТело\n"))
    rules = _rules(run)
    if flagged:
        assert rules == [("MANIFEST_ALLOWED_TOOLS_BASH", "medium", "SKILL.md", 3)]
    else:
        assert rules == []


def test_bang_injection_lines(tmp_path):
    text = "---\nname: s\ndescription: 'не !`echo в frontmatter`'\n---\nСтрока\n!`echo a` и !`echo b`\n`echo c` -- не вставка\n"
    run = manifest_check.run(_skill(tmp_path, text))
    assert _rules(run) == [
        ("MANIFEST_SHELL_INJECTION", "high", "SKILL.md", 6),
        ("MANIFEST_SHELL_INJECTION", "high", "SKILL.md", 6),
    ]
    assert [f.snippet for f in run.findings] == ["!`echo a`", "!`echo b`"]


def test_bang_without_frontmatter_whole_file_is_body(tmp_path):
    run = manifest_check.run(_skill(tmp_path, "!`echo a`\n"))
    assert _rules(run) == [("MANIFEST_SHELL_INJECTION", "high", "SKILL.md", 1)]


def test_bang_findings_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(manifest_check, "MAX_BANG_FINDINGS", 2)
    run = manifest_check.run(_skill(tmp_path, "!`echo 1`\n!`echo 2`\n!`echo 3`\n"))
    assert len(run.findings) == 2
    assert run.warnings == ["SKILL.md: показаны первые 2 из 3 вставок !`…`"]


@pytest.mark.parametrize(
    "text, warning",
    [
        ("---\nname: [broken\n---\n", "frontmatter не разбирается как YAML"),
        ("---\nname: s\n", "frontmatter не закрыт строкой ---"),
        ("---\n- a\n---\n", "frontmatter не является словарём"),
        ("---\nname: !!python/object/apply:os.system ['echo']\n---\n", "frontmatter не разбирается как YAML"),
    ],
)
def test_bad_frontmatter_is_warning(tmp_path, text, warning):
    run = manifest_check.run(_skill(tmp_path, text))
    assert run.ok and run.findings == []
    assert run.warnings[0].startswith(f"SKILL.md: {warning}")


def test_frontmatter_too_big(tmp_path, monkeypatch):
    monkeypatch.setattr(manifest_check, "FRONTMATTER_MAX_BYTES", 50)
    run = manifest_check.run(_skill(tmp_path, "---\nname: s\ndescription: " + "x" * 100 + "\n---\n"))
    assert run.warnings == ["SKILL.md: frontmatter больше 0 КиБ"]


def test_nested_skill_md_checked(tmp_path):
    skill = _skill(tmp_path, "---\nname: s\n---\nok\n")
    (skill / "inner").mkdir()
    (skill / "inner" / "SKILL.md").write_text("---\nname: i\nallowed-tools: Bash\n---\n")
    assert _rules(manifest_check.run(skill)) == [("MANIFEST_ALLOWED_TOOLS_BASH", "medium", "inner/SKILL.md", 3)]


def test_symlinked_skill_md_ignored(tmp_path):
    skill = _skill(tmp_path, "---\nname: s\n---\n")
    outside = tmp_path / "outside.md"
    outside.write_text("!`echo x`\n")
    (skill / "sub").mkdir()
    (skill / "sub" / "SKILL.md").symlink_to(outside)
    assert manifest_check.run(skill).findings == []


def test_clean_skill(tmp_path):
    run = manifest_check.run(_skill(tmp_path, "---\nname: s\ndescription: d\n---\nВыведи `echo ok`.\n"))
    assert run.findings == [] and run.warnings == [] and run.error is None


@pytest.mark.parametrize(
    "case, expected",
    [
        ("hooks-command", ["MANIFEST_HOOKS_COMMAND"]),
        ("bang-injection", ["MANIFEST_SHELL_INJECTION"]),
        ("bang-network", ["MANIFEST_SHELL_INJECTION"]),
        ("shell-persistence", []),
        ("benign-plain", []),
    ],
)
def test_eval_markers(case, expected):
    """Пробелы движков из корпуса (eval): hooks и `!`…`` закрывает эта проверка."""
    assert [f.rule_id for f in manifest_check.run(EVAL_MARKERS / case).findings] == expected
