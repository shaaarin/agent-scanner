"""Запуск движков (Cisco skill-scanner, NVIDIA SkillSpector) и нормализация их JSON.

Модуль нужен подзадаче 1 (сравнение движков на корпусе). Нормализаторы — чистые
функции без запуска процессов, поэтому тестируются на сохранённых JSON.
Адаптеры самого сканера (подзадача 6) будут отдельным кодом в app/.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

SEVERITY_ORDER = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
# Порог «движок поймал»: HIGH и выше — это то, что по D-12 даёт review/block.
DETECT_THRESHOLD = "HIGH"


def sev_rank(sev: str | None) -> int:
    """Числовой ранг severity; неизвестное/пустое значение = ниже INFO (-1)."""
    if not sev:
        return -1
    s = str(sev).upper()
    return SEVERITY_ORDER.index(s) if s in SEVERITY_ORDER else -1


@dataclass
class Finding:
    rule_id: str
    severity: str
    file: str | None = None


@dataclass
class EngineResult:
    engine: str
    ok: bool
    error: str | None = None
    findings: list[Finding] = field(default_factory=list)
    own_verdict: str | None = None  # вердикт самого движка — только для справки (D-10)

    @property
    def max_severity(self) -> str | None:
        best = max(self.findings, key=lambda f: sev_rank(f.severity), default=None)
        return best.severity.upper() if best and sev_rank(best.severity) >= 0 else None

    def detected(self, threshold: str = DETECT_THRESHOLD) -> bool:
        return self.ok and sev_rank(self.max_severity) >= sev_rank(threshold)


def normalize_cisco(data: dict) -> EngineResult:
    """Cisco skill-scanner: {is_safe, max_severity, findings:[{rule_id, severity, file_path}]}."""
    findings = [
        Finding(
            rule_id=str(f.get("rule_id", "")),
            severity=str(f.get("severity", "")).upper(),
            file=f.get("file_path") or f.get("file"),
        )
        for f in data.get("findings", [])
    ]
    verdict = "safe" if data.get("is_safe") else "unsafe"
    return EngineResult("cisco", True, findings=findings, own_verdict=verdict)


def normalize_skillspector(data: dict) -> EngineResult:
    """SkillSpector: {issues:[{id, pattern, severity, location:{file}}], risk_assessment}."""
    findings = []
    for it in data.get("issues", []):
        loc = it.get("location") or {}
        findings.append(
            Finding(
                rule_id=str(it.get("pattern") or it.get("id") or ""),
                severity=str(it.get("severity", "")).upper(),
                file=loc.get("file"),
            )
        )
    verdict = (data.get("risk_assessment") or {}).get("recommendation")
    return EngineResult("skillspector", True, findings=findings, own_verdict=verdict)


def _run(cmd: list[str], out_file: Path, timeout: int) -> tuple[dict | None, str | None]:
    """Запускает CLI; JSON читается из out_file (код возврата у обоих движков не показатель)."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return None, f"timeout {timeout}s"
    except FileNotFoundError as exc:
        return None, f"binary not found: {exc}"
    if not out_file.exists() or out_file.stat().st_size == 0:
        tail = (proc.stderr or proc.stdout or "")[-300:].strip()
        return None, f"no output (rc={proc.returncode}): {tail}"
    try:
        return json.loads(out_file.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as exc:
        return None, f"bad json: {exc}"


def run_cisco(skill_dir: Path, binary: str = "skill-scanner", timeout: int = 300) -> EngineResult:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.json"
        cmd = [binary, "scan", str(skill_dir), "--use-behavioral", "--format", "json", "--output", str(out)]
        data, err = _run(cmd, out, timeout)
    if data is None:
        return EngineResult("cisco", False, error=err)
    return normalize_cisco(data)


def run_skillspector(skill_dir: Path, binary: str = "skillspector", timeout: int = 300) -> EngineResult:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.json"
        cmd = [binary, "scan", str(skill_dir), "--no-llm", "-f", "json", "-o", str(out)]
        data, err = _run(cmd, out, timeout)
    if data is None:
        return EngineResult("skillspector", False, error=err)
    return normalize_skillspector(data)
