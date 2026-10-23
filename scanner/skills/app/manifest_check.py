"""Мини-проверка frontmatter `SKILL.md` (D-31). В отчёте -- движок `manifest`.

Это не третий движок, а разбор структуры, которую YARA не выражает, а Cisco
не видит вовсе (его YARA идёт по телу SKILL.md без frontmatter):

  * `hooks` с shell-командами -- high: Claude Code выполняет их сам, без
    участия модели;
  * `allowed-tools` с `Bash` без ограничений -- medium;
  * `` !`команда` `` в теле -- high: Claude Code выполняет её при загрузке
    скилла. Опасные варианты (сеть, секреты) дополнительно ловит наше
    YARA-правило в обоих движках.

Проверяются все `SKILL.md` внутри папки скилла (вложенные -- часть внешнего).
Файл недоверенный: только `yaml.safe_load`, ограниченный размер, обход
структуры с ограничением глубины (якоря YAML могут дать цикл).
"""
import re
import time
from pathlib import Path

import yaml

from app.engines.base import EngineRun, Finding, clip, sort_key

ENGINE = "manifest"
LABEL = "Проверка frontmatter"
VERSION = "1"
SKILL_FILE = "SKILL.md"
MAX_BYTES = 1024 * 1024  # SKILL.md больше -- проверяем только начало
FRONTMATTER_MAX_BYTES = 64 * 1024
MAX_BANG_FINDINGS = 20
MAX_DEPTH = 20

BANG_RE = re.compile(r"!`([^`\n]+)`")
UNRESTRICTED_BASH = {"bash", "bash(*)", "bash(:*)", "bash(*:*)"}


class Frontmatter:
    """Разобранный SKILL.md: данные frontmatter, тело и номер его первой строки."""

    def __init__(self, data, lines: list[str], body_start: int, error: str | None):
        self.data = data if isinstance(data, dict) else None
        self.lines = lines  # все строки файла (в пределах MAX_BYTES)
        self.body_start = body_start  # индекс первой строки тела (0-based)
        self.error = error


def read_frontmatter(path: Path, max_bytes: int = MAX_BYTES) -> Frontmatter:
    try:
        with path.open("rb") as handle:
            text = handle.read(max_bytes).decode("utf-8", errors="replace")
    except OSError as exc:
        return Frontmatter(None, [], 0, f"не удалось прочитать: {exc.strerror or exc}")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return Frontmatter(None, lines, 0, None)  # frontmatter нет -- всё тело
    end = next((i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    if end is None:
        return Frontmatter(None, lines, 0, "frontmatter не закрыт строкой ---")
    raw = "\n".join(lines[1:end])
    if len(raw.encode("utf-8")) > FRONTMATTER_MAX_BYTES:
        return Frontmatter(None, lines, end + 1, f"frontmatter больше {FRONTMATTER_MAX_BYTES // 1024} КиБ")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return Frontmatter(None, lines, end + 1, f"frontmatter не разбирается как YAML: {str(exc).splitlines()[0]}")
    if data is not None and not isinstance(data, dict):
        return Frontmatter(None, lines, end + 1, "frontmatter не является словарём")
    return Frontmatter(data, lines, end + 1, None)


def _key_line(lines: list[str], key: str) -> int | None:
    pattern = re.compile(rf"^{re.escape(key)}\s*:")
    for index, line in enumerate(lines[1:], start=2):
        if line.strip() == "---":
            return None
        if pattern.match(line):
            return index
    return None


def hook_commands(hooks) -> list[str]:
    """Все shell-команды в `hooks` любой вложенности: `{type: command,
    command: ...}` (формат Claude Code) и `{command: ...}` без типа."""
    commands: list[str] = []
    seen: set[int] = set()

    def walk(node, depth: int) -> None:
        if depth > MAX_DEPTH or id(node) in seen:
            return
        if isinstance(node, dict):
            seen.add(id(node))
            command = node.get("command")
            if isinstance(command, str) and command.strip() and node.get("type", "command") == "command":
                commands.append(command.strip())
            for value in node.values():
                walk(value, depth + 1)
        elif isinstance(node, list):
            seen.add(id(node))
            for value in node:
                walk(value, depth + 1)

    walk(hooks, 0)
    return commands


def allowed_tools(value) -> list[str]:
    if isinstance(value, str):
        return [part for part in re.split(r"[,\s]+(?![^()]*\))", value) if part]
    if isinstance(value, list):
        return [str(item).strip() for item in value if isinstance(item, (str, int, float)) and str(item).strip()]
    return []


def check_file(path: Path, relative: str) -> tuple[list[Finding], list[str]]:
    fm = read_frontmatter(path)
    findings: list[Finding] = []
    warnings = [f"{relative}: {fm.error}"] if fm.error else []
    data = fm.data or {}

    commands = hook_commands(data.get("hooks")) if "hooks" in data else []
    if commands:
        shown = "; ".join(commands[:3]) + (f" (и ещё {len(commands) - 3})" if len(commands) > 3 else "")
        findings.append(
            Finding(
                engine=ENGINE,
                rule_id="MANIFEST_HOOKS_COMMAND",
                severity="high",
                confidence=None,
                category="command_injection",
                file=relative,
                line=_key_line(fm.lines, "hooks"),
                title="Скилл регистрирует hooks с shell-командами",
                finding=f"Во frontmatter объявлены hooks Claude Code с командами ({len(commands)}). "
                "Они выполняются автоматически при событиях агента, без участия модели и подтверждения пользователя.",
                fix="Уберите hooks из скилла или проверьте каждую команду вручную перед установкой.",
                snippet=clip(shown, 500),
            )
        )

    tools = allowed_tools(data.get("allowed-tools"))
    unrestricted = [tool for tool in tools if tool.replace(" ", "").lower() in UNRESTRICTED_BASH]
    if unrestricted:
        findings.append(
            Finding(
                engine=ENGINE,
                rule_id="MANIFEST_ALLOWED_TOOLS_BASH",
                severity="medium",
                confidence=None,
                category="unauthorized_tool_use",
                file=relative,
                line=_key_line(fm.lines, "allowed-tools"),
                title="allowed-tools разрешает Bash без ограничений",
                finding="Скилл получает право выполнять любые shell-команды без запроса подтверждения.",
                fix="Сузьте разрешение до конкретных команд, например Bash(git status:*).",
                snippet=clip(", ".join(tools), 500),
            )
        )

    bangs = 0
    for index in range(fm.body_start, len(fm.lines)):
        for match in BANG_RE.finditer(fm.lines[index]):
            bangs += 1
            if bangs > MAX_BANG_FINDINGS:
                continue
            findings.append(
                Finding(
                    engine=ENGINE,
                    rule_id="MANIFEST_SHELL_INJECTION",
                    severity="high",
                    confidence=None,
                    category="command_injection",
                    file=relative,
                    line=index + 1,
                    title="Shell-команда выполняется при загрузке скилла (!`…`)",
                    finding="Claude Code выполняет команду в !`…` при загрузке скилла и подставляет вывод в контекст, без участия модели.",
                    fix="Уберите !`…` или убедитесь, что команда безопасна и не обращается к сети и секретам.",
                    snippet=clip(match.group(0), 500),
                )
            )
    if bangs > MAX_BANG_FINDINGS:
        warnings.append(f"{relative}: показаны первые {MAX_BANG_FINDINGS} из {bangs} вставок !`…`")
    return findings, warnings


def run(skill_dir: Path) -> EngineRun:
    started = time.monotonic()
    result = EngineRun(ENGINE, "ok", VERSION)
    files = sorted(
        path for path in skill_dir.rglob(SKILL_FILE) if path.is_file() and not path.is_symlink()
    )
    for path in files:
        findings, warnings = check_file(path, path.relative_to(skill_dir).as_posix())
        result.findings.extend(findings)
        result.warnings.extend(warnings)
    result.findings.sort(key=sort_key)
    result.duration_sec = round(time.monotonic() - started, 3)
    return result
