"""Cisco AI Defense skill-scanner 2.1.0 (D-17): статика + поведенческий
анализ скриптов, без LLM и без внешних сервисов (VirusTotal, AI Defense, OSV
у Cisco не включаются). Код возврата 0 и при находках (без
`--fail-on-*`). Самопроверку правил Cisco (`scan_metadata.rule_contract`) не
показываем: это внутреннее состояние движка, а не свойство скилла."""
from pathlib import Path

from app.engines.base import (
    Engine,
    EngineOutputError,
    EngineRun,
    Finding,
    MAX_SNIPPET,
    as_dict,
    clip,
    normalize_severity,
    relative_file,
    rules_dir,
    to_int,
)

GENERIC_YARA_TITLE = "detected by YARA"


class CiscoEngine(Engine):
    name = "cisco"
    label = "Cisco skill-scanner"
    version = "2.1.0"
    binary_env = "CISCO_BIN"
    default_binary = "/opt/engines/cisco/bin/skill-scanner"

    @staticmethod
    def rule_pack() -> Path:
        return rules_dir() / "cisco-pack"

    def command(self, skill_dir: Path, output: Path) -> list[str]:
        cmd = [self.binary, "scan", str(skill_dir), "--use-behavioral"]
        if (self.rule_pack() / "pack.yaml").is_file():
            # Не --custom-rules: тот заменяет встроенные YARA-правила Cisco (D-18).
            cmd += ["--trusted-rule-pack", str(self.rule_pack())]
        return cmd + ["--format", "json", "--output", str(output)]

    def missing_rules(self) -> str | None:
        if (self.rule_pack() / "pack.yaml").is_file():
            return None
        return "свои YARA-правила не подключены: нет пака rules/cisco-pack (собирается при сборке образа)"

    def parse(self, data: dict, skill_dir: Path, run: EngineRun) -> None:
        if "findings" not in data or not isinstance(data["findings"], list):
            raise EngineOutputError("в отчёте Cisco нет списка findings")
        if "is_safe" in data:
            run.own_verdict = "safe" if data.get("is_safe") else "unsafe"
        for item in data["findings"]:
            item = as_dict(item)
            if not item:
                continue
            run.findings.append(
                Finding(
                    engine=self.name,
                    rule_id=str(item.get("rule_id") or item.get("id") or "unknown"),
                    severity=normalize_severity(item.get("severity")),
                    confidence=None,  # у Cisco нет (D-34)
                    category=clip(item.get("category"), 100),
                    file=relative_file(item.get("file_path"), skill_dir),
                    line=to_int(item.get("line_number")),
                    title=_title(item),
                    finding=clip(item.get("description")),
                    fix=clip(item.get("remediation")),
                    snippet=clip(item.get("snippet"), MAX_SNIPPET),
                )
            )


def _title(item: dict) -> str:
    """У YARA-находок Cisco заголовок общий («… detected by YARA»), а смысл --
    в описании «<meta.description>: <совпадение>»."""
    title = clip(item.get("title"))
    description = str(item.get("description") or "")
    if (not title or GENERIC_YARA_TITLE in title) and str(item.get("rule_id", "")).startswith("YARA_") and description:
        return clip(description.split(": ", 1)[0], 300)
    return title or str(item.get("rule_id") or "Находка Cisco")
