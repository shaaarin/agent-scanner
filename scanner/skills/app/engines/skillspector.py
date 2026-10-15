"""NVIDIA SkillSpector v2.11.2 (D-17) в режиме `--no-llm`: статические
правила, YARA, проверка зависимостей с запросом в OSV.dev (D-26).

Без сети SkillSpector молча берёт встроенные данные и оценивает зависимости
строже (R-32): об этом он пишет только в stderr -- адаптер переносит это в
предупреждение прогона (D-50). Вердикт самого движка (`recommendation`) --
справочно (D-10)."""
import json
import os
import re
from pathlib import Path

from app.engines.base import (
    Engine,
    EngineOutputError,
    EngineRun,
    Finding,
    MAX_SNIPPET,
    as_dict,
    as_list,
    clip,
    normalize_severity,
    relative_file,
    rules_dir,
    to_confidence,
    to_int,
)

# pattern YARA-находки: "YARA rule '<имя>': <meta.description> [<категория>]".
YARA_PATTERN_RE = re.compile(r"YARA rule '([A-Za-z0-9_]+)'(?::\s*(.*?))?(?:\s*\[[^\]]*\])?$")
OSV_FALLBACK_MARKERS = ("OSV.dev API request failed", "OSV.dev API request timed out", "OSV.dev unreachable")
OSV_WARNING = "OSV.dev недоступен — уязвимости зависимостей оценены по встроенным данным SkillSpector, severity может быть завышена"


class SkillSpectorEngine(Engine):
    name = "skillspector"
    label = "NVIDIA SkillSpector"
    version = "2.11.2"
    binary_env = "SKILLSPECTOR_BIN"
    default_binary = "/opt/engines/skillspector/bin/skillspector"
    # 1 -- «риск выше порога», отчёт записан; 2 -- ошибка (cli.py v2.11.2).
    ok_returncodes = (0, 1)

    @staticmethod
    def yara_dir() -> Path:
        return rules_dir() / "yara"

    def _has_rules(self) -> bool:
        return self.yara_dir().is_dir() and any(self.yara_dir().glob("*.yara"))

    def command(self, skill_dir: Path, output: Path) -> list[str]:
        cmd = [self.binary, "scan", str(skill_dir), "--no-llm"]
        if self._has_rules():
            # Добавляются к встроенным правилам SkillSpector (D-18).
            cmd += ["--yara-rules-dir", str(self.yara_dir())]
        return cmd + ["-f", "json", "-o", str(output)]

    def missing_rules(self) -> str | None:
        return None if self._has_rules() else "свои YARA-правила не подключены: нет rules/yara"

    def extra_env(self) -> dict[str, str]:
        # Таймаут запроса в OSV.dev можно задать в compose; больше ничего из
        # окружения сервиса движку не передаём.
        value = os.environ.get("SKILLSPECTOR_OSV_TIMEOUT")
        return {"SKILLSPECTOR_OSV_TIMEOUT": value} if value else {}

    def parse(self, data: dict, skill_dir: Path, run: EngineRun) -> None:
        if "issues" not in data or not isinstance(data["issues"], list):
            raise EngineOutputError("в отчёте SkillSpector нет списка issues")
        if data.get("execution_successful") is False:
            raise EngineOutputError("SkillSpector сообщил execution_successful=false")
        metadata = as_dict(data.get("metadata"))
        version = metadata.get("skillspector_version")
        if version and str(version) != self.version:
            run.warnings.append(f"SkillSpector сообщил версию {version}, ожидалась {self.version}")
        run.own_verdict = as_dict(data.get("risk_assessment")).get("recommendation")
        for item in data["issues"]:
            item = as_dict(item)
            if not item:
                continue
            location = as_dict(item.get("location"))
            category = clip(item.get("category"), 100)
            pattern = clip(item.get("pattern"), 300)
            yara_rule = YARA_PATTERN_RE.match(str(item.get("pattern") or ""))
            run.findings.append(
                Finding(
                    engine=self.name,
                    # Все YARA-находки SkillSpector -- id YR1; берём имя правила,
                    # как у Cisco (YARA_<имя>), чтобы находки сопоставлялись.
                    rule_id=f"YARA_{yara_rule.group(1)}" if yara_rule else str(item.get("id") or "unknown"),
                    severity=normalize_severity(item.get("severity")),
                    confidence=to_confidence(item.get("confidence")),
                    category=category,
                    file=relative_file(location.get("file"), skill_dir),
                    line=to_int(location.get("start_line")),
                    title=(yara_rule and clip(yara_rule.group(2), 300))
                    or pattern
                    or category
                    or str(item.get("id") or "Находка SkillSpector"),
                    finding=clip(item.get("explanation")),
                    fix=clip(item.get("remediation")),
                    snippet=clip(item.get("finding") or item.get("code_snippet"), MAX_SNIPPET),
                )
            )
        completeness = as_dict(data.get("analysis_completeness"))
        if completeness.get("is_complete") is False:
            run.warnings.append(_incomplete_warning(completeness))
        if any("OSV.dev unreachable" in json.dumps(i, ensure_ascii=False) for i in data["issues"]):
            self._osv_warning(run)

    def inspect_stderr(self, stderr: str, run: EngineRun) -> None:
        if any(marker in stderr for marker in OSV_FALLBACK_MARKERS):
            self._osv_warning(run)

    @staticmethod
    def _osv_warning(run: EngineRun) -> None:
        if OSV_WARNING not in run.warnings:
            run.warnings.append(OSV_WARNING)


def _incomplete_warning(completeness: dict) -> str:
    """Анализ неполный: покрытие файлов (если < 100%), анализаторы, которые
    пропустили работу (degraded/failed), и исключения из журнала инспекции
    (например, ссылка в SKILL.md на отсутствующий файл)."""
    names = sorted(
        str(status.get("analyzer_id"))
        for status in as_list(completeness.get("analyzer_statuses"))
        if isinstance(status, dict) and status.get("status") in ("degraded", "failed")
    )
    text = "SkillSpector выполнил анализ не полностью"
    details = []
    coverage = completeness.get("coverage_percent")
    if isinstance(coverage, (int, float)) and coverage < 100:
        details.append(f"проверено {coverage}% файлов")
    if names:
        shown = ", ".join(names[:5]) + (f" и ещё {len(names) - 5}" if len(names) > 5 else "")
        details.append(f"часть проверок пропущена: {shown}")
    exceptions = [e for e in as_list(completeness.get("ledger_exceptions")) if isinstance(e, dict)]
    unresolved = sum(1 for e in exceptions if e.get("reason_code") == "reference_unresolved")
    if unresolved:
        details.append(f"не найдено файлов по ссылкам из скилла: {unresolved}")
    other = sorted({str(e.get("reason_code")) for e in exceptions if e.get("reason_code") != "reference_unresolved"})
    if other:
        details.append(f"прочие ограничения: {', '.join(other[:5])}")
    return text + (f" ({'; '.join(details)})" if details else "")
