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
    to_int,
)


class CiscoEngine(Engine):
    name = "cisco"
    label = "Cisco skill-scanner"
    version = "2.1.0"
    binary_env = "CISCO_BIN"
    default_binary = "/opt/engines/cisco/bin/skill-scanner"

    def command(self, skill_dir: Path, output: Path) -> list[str]:
        return [
            self.binary, "scan", str(skill_dir),
            "--use-behavioral",
            "--format", "json",
            "--output", str(output),
        ]

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
                    title=clip(item.get("title")) or str(item.get("rule_id") or "Находка Cisco"),
                    finding=clip(item.get("description")),
                    fix=clip(item.get("remediation")),
                    snippet=clip(item.get("snippet"), MAX_SNIPPET),
                )
            )
