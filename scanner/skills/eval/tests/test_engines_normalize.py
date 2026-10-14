"""Нормализация JSON движков — чистые функции, без запуска процессов."""
import json
import subprocess
import sys

import pytest

from engines import (
    EngineResult,
    Finding,
    normalize_cisco,
    normalize_skillspector,
    run_cisco,
    run_skillspector,
    sev_rank,
)


def test_sev_rank_order_and_unknown():
    assert sev_rank("critical") > sev_rank("HIGH") > sev_rank("medium") > sev_rank("LOW") > sev_rank("INFO") > -1
    assert sev_rank(None) == -1
    assert sev_rank("SAFE") == -1
    assert sev_rank("weird") == -1


def test_normalize_cisco_basic():
    data = {
        "is_safe": False,
        "max_severity": "HIGH",
        "findings": [
            {"rule_id": "A", "severity": "low", "file_path": "x.py"},
            {"rule_id": "B", "severity": "HIGH", "file_path": "SKILL.md"},
        ],
    }
    res = normalize_cisco(data)
    assert res.ok and res.engine == "cisco"
    assert res.max_severity == "HIGH"
    assert res.detected()
    assert res.own_verdict == "unsafe"
    assert [f.rule_id for f in res.findings] == ["A", "B"]


def test_normalize_cisco_clean():
    res = normalize_cisco({"is_safe": True, "max_severity": "SAFE", "findings": []})
    assert res.max_severity is None
    assert not res.detected()
    assert res.own_verdict == "safe"


def test_normalize_skillspector_basic():
    data = {
        "risk_assessment": {"recommendation": "DO_NOT_INSTALL", "max_issue_severity": "CRITICAL"},
        "issues": [
            {"id": "YR1", "pattern": "YARA rule 'x'", "severity": "MEDIUM", "location": {"file": "a.sh"}},
            {"id": "YR2", "pattern": None, "severity": "critical", "location": None},
        ],
    }
    res = normalize_skillspector(data)
    assert res.max_severity == "CRITICAL"
    assert res.detected()
    assert res.own_verdict == "DO_NOT_INSTALL"
    assert res.findings[0].file == "a.sh"
    assert res.findings[1].rule_id == "YR2"  # без pattern берётся id
    assert res.findings[1].file is None


def test_normalize_skillspector_empty():
    res = normalize_skillspector({"issues": []})
    assert res.findings == [] and not res.detected() and res.own_verdict is None


def test_detected_threshold_and_failed_engine():
    medium = EngineResult("cisco", True, findings=[Finding("r", "MEDIUM")])
    assert not medium.detected()
    assert medium.detected("MEDIUM")
    failed = EngineResult("cisco", False, error="boom", findings=[Finding("r", "CRITICAL")])
    assert not failed.detected()  # упавший движок ничего не «поймал»


def test_run_missing_binary_is_reported_not_raised(tmp_path):
    res = run_cisco(tmp_path, binary="/nonexistent/skill-scanner")
    assert not res.ok and "not found" in res.error
    res = run_skillspector(tmp_path, binary="/nonexistent/skillspector")
    assert not res.ok and "not found" in res.error


def test_run_without_output_file_is_error(tmp_path):
    # команда существует, но JSON не пишет
    res = run_cisco(tmp_path, binary="true")
    assert not res.ok and "no output" in res.error


def test_run_timeout(tmp_path):
    script = tmp_path / "slow.py"
    script.write_text("import time; time.sleep(5)\n")
    wrapper = tmp_path / "slow"
    wrapper.write_text(f"#!/bin/sh\nexec {sys.executable} {script}\n")
    wrapper.chmod(0o755)
    res = run_skillspector(tmp_path, binary=str(wrapper), timeout=1)
    assert not res.ok and "timeout" in res.error


def test_run_bad_json(tmp_path):
    fake = tmp_path / "fake"
    # аргумент после --output — путь выходного файла
    fake.write_text("#!/bin/sh\nwhile [ $# -gt 0 ]; do if [ \"$1\" = --output ]; then echo '{bad' > \"$2\"; fi; shift; done\n")
    fake.chmod(0o755)
    res = run_cisco(tmp_path, binary=str(fake))
    assert not res.ok and "bad json" in res.error


def test_run_reads_json_from_fake_engine(tmp_path):
    fake = tmp_path / "fake"
    payload = json.dumps({"is_safe": False, "max_severity": "HIGH", "findings": [{"rule_id": "R", "severity": "HIGH"}]})
    fake.write_text(
        "#!/bin/sh\nwhile [ $# -gt 0 ]; do if [ \"$1\" = --output ]; then cat > \"$2\" <<'EOF'\n" + payload + "\nEOF\nfi; shift; done\n"
    )
    fake.chmod(0o755)
    res = run_cisco(tmp_path, binary=str(fake))
    assert res.ok and res.detected() and res.findings[0].rule_id == "R"
