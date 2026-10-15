"""Адаптеры движков (D-11, D-23, D-37, D-50): разбор настоящих отчётов и
запуск CLI в отдельном процессе с подставным исполняемым файлом."""
import json

import pytest

from app import engines
from app.engines import base
from app.engines.base import EngineRun, normalize_severity, relative_file
from app.engines.skillspector import OSV_WARNING

from engine_fakes import FIXTURES, fixture_body, install, install_fixture, offline_stderr


def _parse(engine: str, fixture: str, skill_dir) -> EngineRun:
    run = EngineRun(engine, "ok", engines.get(engine).version)
    data = json.loads((FIXTURES / fixture).read_text())
    engines.get(engine).parse(data, skill_dir, run)
    return run


# --- нормализация -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [("CRITICAL", "critical"), ("High", "high"), ("medium", "medium"), ("LOW", "low"), ("INFO", "info"),
     ("SAFE", "info"), (None, "medium"), ("weird", "medium")],
)
def test_normalize_severity(raw, expected):
    assert normalize_severity(raw) == expected


def test_relative_file(tmp_path):
    skill = tmp_path / "skill"
    assert relative_file("scripts/a.py", skill) == "scripts/a.py"
    assert relative_file("./SKILL.md", skill) == "SKILL.md"
    assert relative_file(str(skill / "x" / "y.sh"), skill) == "x/y.sh"
    assert relative_file("/tmp/elsewhere/z.py", skill) == "z.py"
    assert relative_file("a\\b.py", skill) == "a/b.py"
    assert relative_file(None, skill) is None


def test_clip():
    assert base.clip("  ") is None
    assert base.clip("x" * 10, 5) == "xxxx…"


# --- разбор настоящих отчётов ---------------------------------------------------------------


def test_parse_cisco(tmp_path):
    run = _parse("cisco", "cisco-environment-secrets.json", tmp_path)
    assert run.own_verdict == "unsafe"
    [finding] = run.findings
    assert finding.as_dict() == {
        "engine": "cisco",
        "rule_id": "DATA_EXFIL_SENSITIVE_FILES",
        "severity": "high",
        "confidence": None,
        "category": "data_exfiltration",
        "file": "get_info.py",
        "line": 18,
        "title": "Opening sensitive system or credential files",
        "finding": 'Pattern detected: open("/etc/shadow',
        "fix": "Do not read credential files or sensitive system files",
        "snippet": 'return open("/etc/shadow").read()',
    }
    assert run.warnings == []


def test_parse_cisco_clean(tmp_path):
    run = _parse("cisco", "cisco-benign-plain.json", tmp_path)
    assert run.own_verdict == "safe"
    assert all(f.severity in ("low", "info", "medium") for f in run.findings)


def test_parse_skillspector(tmp_path):
    run = _parse("skillspector", "skillspector-environment-secrets.json", tmp_path)
    assert run.own_verdict == "CAUTION"
    by_id = {f.rule_id: f for f in run.findings}
    pe3 = by_id["PE3"]
    assert (pe3.severity, pe3.confidence, pe3.category, pe3.file, pe3.line) == (
        "high", 0.95, "Privilege Escalation", "get_info.py", 18
    )
    assert pe3.title == "Credential Access"
    assert pe3.snippet == "/etc/shadow"
    assert pe3.fix.startswith("Remove references to credential paths")
    lp3 = by_id["LP3"]
    assert lp3.title == "MCP Least Privilege"  # pattern пуст -- заголовок из категории
    assert run.warnings == []


def test_skillspector_osv_online_no_warning(tmp_path):
    run = _parse("skillspector", "skillspector-unpinned-online.json", tmp_path)
    assert OSV_WARNING not in run.warnings
    assert {f.severity for f in run.findings} == {"low"}


def test_skillspector_osv_offline_warning_from_report(tmp_path):
    run = _parse("skillspector", "skillspector-unpinned-offline.json", tmp_path)
    # Без OSV SkillSpector сам помечает анализ зависимостей деградировавшим.
    assert run.warnings == [
        "SkillSpector выполнил анализ не полностью (проверено 66.7% файлов; "
        "часть проверок пропущена: static_patterns_supply_chain; прочие ограничения: analyzer_runtime_error)",
        OSV_WARNING,
    ]


def test_skillspector_osv_offline_warning_from_stderr():
    run = EngineRun("skillspector", "ok", "2.11.2")
    engines.get("skillspector").inspect_stderr(offline_stderr(), run)
    engines.get("skillspector").inspect_stderr(offline_stderr(), run)
    assert run.warnings == [OSV_WARNING]


def test_skillspector_incomplete_and_version_warnings(tmp_path):
    data = json.loads((FIXTURES / "skillspector-environment-secrets.json").read_text())
    completeness = data["analysis_completeness"]
    completeness["is_complete"] = False  # покрытие 100%, но анализаторы пропустили работу
    for status in completeness["analyzer_statuses"][:7]:
        status["status"] = "degraded"
    data["metadata"]["skillspector_version"] = "2.12.0"
    run = EngineRun("skillspector", "ok", "2.11.2")
    engines.get("skillspector").parse(data, tmp_path, run)
    [incomplete] = [w for w in run.warnings if "не полностью" in w]
    assert "проверено" not in incomplete
    assert incomplete.startswith("SkillSpector выполнил анализ не полностью (часть проверок пропущена: ")
    assert incomplete.endswith(" и ещё 2)")
    assert "SkillSpector сообщил версию 2.12.0, ожидалась 2.11.2" in run.warnings


def test_skillspector_unresolved_references(tmp_path):
    completeness = {
        "is_complete": False,
        "coverage_percent": 100.0,
        "ledger_exceptions": [
            {"reason_code": "reference_unresolved", "path": "SKILL.md", "start_line": 82},
            {"reason_code": "reference_unresolved", "path": "SKILL.md", "start_line": 115},
            {"reason_code": "file_too_large", "path": "big.bin"},
        ],
    }
    run = EngineRun("skillspector", "ok", "2.11.2")
    engines.get("skillspector").parse({"issues": [], "analysis_completeness": completeness}, tmp_path, run)
    assert run.warnings == [
        "SkillSpector выполнил анализ не полностью (не найдено файлов по ссылкам из скилла: 2; "
        "прочие ограничения: file_too_large)"
    ]


def test_skillspector_incomplete_without_details(tmp_path):
    run = EngineRun("skillspector", "ok", "2.11.2")
    engines.get("skillspector").parse({"issues": [], "analysis_completeness": {"is_complete": False}}, tmp_path, run)
    assert run.warnings == ["SkillSpector выполнил анализ не полностью"]


def test_unknown_fields_ignored_missing_become_none(tmp_path):
    run = EngineRun("cisco", "ok", "2.1.0")
    engines.get("cisco").parse({"findings": [{"severity": "HIGH", "new_field": 1}, "мусор"]}, tmp_path, run)
    [finding] = run.findings
    assert finding.rule_id == "unknown" and finding.file is None and finding.line is None
    assert finding.title == "Находка Cisco"


@pytest.mark.parametrize(
    "engine, data, message",
    [
        ("cisco", {"is_safe": True}, "нет списка findings"),
        ("skillspector", {"issues": None}, "нет списка issues"),
        ("skillspector", {"issues": [], "execution_successful": False}, "execution_successful=false"),
    ],
)
def test_broken_report_structure(tmp_path, engine, data, message):
    with pytest.raises(base.EngineOutputError, match=message):
        engines.get(engine).parse(data, tmp_path, EngineRun(engine, "ok", ""))


# --- запуск процесса ------------------------------------------------------------------------


@pytest.fixture
def skill(tmp_path):
    path = tmp_path / "skill"
    path.mkdir()
    (path / "SKILL.md").write_text("---\nname: s\n---\n")
    return path


def test_run_cisco_with_fake_binary(tmp_path, monkeypatch, skill):
    script = install_fixture(tmp_path, monkeypatch, "cisco", "cisco-environment-secrets.json")
    assert engines.get("cisco").command(skill, tmp_path / "o.json")[:3] == [str(script), "scan", str(skill)]
    run = engines.get("cisco").run(skill, workdir=tmp_path / "run", timeout=30)
    assert run.status == "ok", run.error
    assert run.version == "2.1.0" and run.llm is False
    assert [f.rule_id for f in run.findings] == ["DATA_EXFIL_SENSITIVE_FILES"]
    assert run.duration_sec >= 0


def test_run_skillspector_offline_stderr(tmp_path, monkeypatch, skill):
    install_fixture(
        tmp_path, monkeypatch, "skillspector", "skillspector-unpinned-online.json", stderr=offline_stderr()
    )
    run = engines.get("skillspector").run(skill, workdir=tmp_path / "run", timeout=30)
    assert run.ok and run.warnings == [OSV_WARNING]


def test_command_flags(tmp_path, rules_env):
    out = tmp_path / "o.json"
    cisco = engines.get("cisco").command(tmp_path, out)
    assert "--use-behavioral" in cisco and "--use-llm" not in cisco and "--use-osv" not in cisco
    assert "--custom-rules" not in cisco  # заменил бы встроенные правила Cisco (D-18)
    assert cisco[cisco.index("--trusted-rule-pack") + 1] == str(rules_env / "cisco-pack")
    assert cisco[-2:] == ["--output", str(out)]
    spector = engines.get("skillspector").command(tmp_path, out)
    assert "--no-llm" in spector and spector[-2:] == ["-o", str(out)]
    assert spector[spector.index("--yara-rules-dir") + 1] == str(rules_env / "yara")
    assert engines.get("cisco").missing_rules() is None
    assert engines.get("skillspector").missing_rules() is None


def test_missing_rules_warn_and_run_without(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILLS_RULES_DIR", str(tmp_path / "no-rules"))
    out = tmp_path / "o.json"
    assert "--trusted-rule-pack" not in engines.get("cisco").command(tmp_path, out)
    assert "--yara-rules-dir" not in engines.get("skillspector").command(tmp_path, out)
    assert "rules/cisco-pack" in engines.get("cisco").missing_rules()
    assert "rules/yara" in engines.get("skillspector").missing_rules()


def test_missing_rules_warning_in_run(tmp_path, monkeypatch, skill):
    install_fixture(tmp_path, monkeypatch, "cisco", "cisco-benign-plain.json")
    monkeypatch.setenv("SKILLS_RULES_DIR", str(tmp_path / "no-rules"))
    run = engines.get("cisco").run(skill, workdir=tmp_path / "run", timeout=30)
    assert run.ok and run.warnings == [engines.get("cisco").missing_rules()]


def test_default_rules_dir(monkeypatch):
    monkeypatch.delenv("SKILLS_RULES_DIR")
    assert base.rules_dir() == base.DEFAULT_RULES_DIR
    assert (base.DEFAULT_RULES_DIR / "yara").is_dir()


def test_own_yara_rule_same_id_in_both_engines(tmp_path):
    """Своё YARA-правило: у обоих движков rule_id YARA_<имя> и заголовок из meta."""
    rule = "YARA_skills_shell_rc_persistence"
    title = "Script appends to a shell startup file (persistence)"
    cisco = _parse("cisco", "cisco-shell-persistence-rules.json", tmp_path)
    spector = _parse("skillspector", "skillspector-shell-persistence-rules.json", tmp_path)
    for run in (cisco, spector):
        [own] = [f for f in run.findings if f.rule_id == rule]
        assert (own.severity, own.file, own.line, own.title) == ("high", "scripts/setup.sh", 3, title)
    # Встроенные YARA-правила SkillSpector (все -- id YR1) тоже получают имя.
    assert "YARA_backdoor_persistence" in {f.rule_id for f in spector.findings}
    assert "YR1" not in {f.rule_id for f in spector.findings}


def test_default_binaries(monkeypatch):
    monkeypatch.delenv("CISCO_BIN", raising=False)
    monkeypatch.delenv("SKILLSPECTOR_BIN", raising=False)
    assert engines.get("cisco").binary == "/opt/engines/cisco/bin/skill-scanner"
    assert engines.get("skillspector").binary == "/opt/engines/skillspector/bin/skillspector"


def test_engine_env_is_minimal(tmp_path, monkeypatch, skill):
    monkeypatch.setenv("SECRET_FROM_SERVICE", "do-not-leak")
    install(
        tmp_path,
        monkeypatch,
        "cisco",
        """
        import os
        Path(skill_dir.parent / "env.json").write_text(json.dumps(dict(os.environ)))
        output.write_text(json.dumps({"findings": []}))
        """,
    )
    run = engines.get("cisco").run(skill, workdir=tmp_path / "run", timeout=30)
    assert run.ok, run.error
    env = json.loads((tmp_path / "env.json").read_text())
    assert "SECRET_FROM_SERVICE" not in env
    assert env["HOME"] == str(tmp_path / "run" / "home")
    assert env["TMPDIR"] == env["HOME"]


def test_skillspector_osv_timeout_forwarded(tmp_path, monkeypatch, skill):
    monkeypatch.setenv("SKILLSPECTOR_OSV_TIMEOUT", "7")
    install(
        tmp_path,
        monkeypatch,
        "skillspector",
        """
        import os
        Path(skill_dir.parent / "env.json").write_text(json.dumps(dict(os.environ)))
        output.write_text(json.dumps({"issues": []}))
        """,
    )
    assert engines.get("skillspector").run(skill, workdir=tmp_path / "run", timeout=30).ok
    assert json.loads((tmp_path / "env.json").read_text())["SKILLSPECTOR_OSV_TIMEOUT"] == "7"


def test_skillspector_rc1_is_high_risk_not_error(tmp_path, monkeypatch, skill):
    """SkillSpector выходит с 1, когда риск выше порога; отчёт при этом валиден."""
    install(tmp_path, monkeypatch, "skillspector", fixture_body("skillspector-environment-secrets.json") + "\nsys.exit(1)")
    run = engines.get("skillspector").run(skill, workdir=tmp_path / "run", timeout=30)
    assert run.ok, run.error
    assert {f.rule_id for f in run.findings} == {"PE3", "LP3"}


def test_skillspector_rc2_is_error(tmp_path, monkeypatch, skill):
    install(tmp_path, monkeypatch, "skillspector", fixture_body("skillspector-environment-secrets.json") + "\nsys.exit(2)")
    run = engines.get("skillspector").run(skill, workdir=tmp_path / "run", timeout=30)
    assert run.status == "failed" and run.error.startswith("код возврата 2")


def test_cisco_rc1_is_error(tmp_path, monkeypatch, skill):
    install(tmp_path, monkeypatch, "cisco", fixture_body("cisco-environment-secrets.json") + "\nsys.exit(1)")
    assert engines.get("cisco").run(skill, workdir=tmp_path / "run", timeout=30).status == "failed"


def test_engine_crash(tmp_path, monkeypatch, skill):
    install(tmp_path, monkeypatch, "cisco", "sys.stderr.write('Traceback: boom\\n'); sys.exit(2)")
    run = engines.get("cisco").run(skill, workdir=tmp_path / "run", timeout=30)
    assert run.status == "failed"
    assert run.error == "код возврата 2: Traceback: boom"
    assert run.findings == []


def test_engine_timeout(tmp_path, monkeypatch, skill):
    install(tmp_path, monkeypatch, "skillspector", "time.sleep(30)")
    run = engines.get("skillspector").run(skill, workdir=tmp_path / "run", timeout=0.5)
    assert run.status == "timeout"
    assert "превышен таймаут" in run.error


def test_engine_missing_binary(tmp_path, monkeypatch, skill):
    monkeypatch.setenv("CISCO_BIN", str(tmp_path / "nope"))
    run = engines.get("cisco").run(skill, workdir=tmp_path / "run", timeout=5)
    assert run.status == "failed" and "не удалось запустить" in run.error


@pytest.mark.parametrize(
    "body, message",
    [
        ("pass", "без отчёта"),
        ("output.write_text('')", "без отчёта"),
        ("output.write_text('{not json')", "не является JSON"),
        ("output.write_text('[1, 2]')", "не является JSON-объектом"),
        ("output.write_text(json.dumps({'is_safe': True}))", "нет списка findings"),
    ],
)
def test_engine_bad_report(tmp_path, monkeypatch, skill, body, message):
    install(tmp_path, monkeypatch, "cisco", body)
    run = engines.get("cisco").run(skill, workdir=tmp_path / "run", timeout=30)
    assert run.status == "failed"
    assert message in run.error


def test_engine_report_too_big(tmp_path, monkeypatch, skill):
    monkeypatch.setattr(base, "MAX_REPORT_BYTES", 100)
    install(tmp_path, monkeypatch, "cisco", "output.write_text(json.dumps({'findings': [], 'pad': 'x' * 200}))")
    run = engines.get("cisco").run(skill, workdir=tmp_path / "run", timeout=30)
    assert run.status == "failed" and "больше" in run.error


def test_findings_capped_and_sorted(tmp_path, monkeypatch, skill):
    monkeypatch.setattr(base, "MAX_FINDINGS", 3)
    install(
        tmp_path,
        monkeypatch,
        "cisco",
        """
        sev = ["LOW", "CRITICAL", "INFO", "HIGH", "MEDIUM"]
        output.write_text(json.dumps({"findings": [
            {"rule_id": f"R{i}", "severity": s, "file_path": "a.py", "line_number": i} for i, s in enumerate(sev)
        ]}))
        """,
    )
    run = engines.get("cisco").run(skill, workdir=tmp_path / "run", timeout=30)
    assert [f.severity for f in run.findings] == ["critical", "high", "medium"]
    assert run.warnings == ["показаны первые 3 находок из 5"]


def test_llm_not_supported_in_mvp(tmp_path, skill):
    with pytest.raises(NotImplementedError, match="LLM-анализ отключён"):
        engines.get("cisco").run(skill, workdir=tmp_path / "run", timeout=5, llm={"model": "x"})


def test_registry_matches_runner():
    from app import runner

    assert list(engines.ENGINES) == list(runner.ENGINES)
