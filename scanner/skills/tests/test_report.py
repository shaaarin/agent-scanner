"""Отчёт `Scan.results` (§2.7, D-36) и вердикт (D-10, D-12 в редакции D-52,
D-13, D-23, D-34)."""
import json

import pytest

from app import report
from app.context import Deadline, ScanContext
from app.engines.base import EngineRun, Finding
from app.engines.skillspector import OSV_WARNING

from engine_fakes import FIXTURES


def _f(engine, severity, rule_id="R", file="a.py", line=1, title="t", confidence=None):
    return Finding(engine, rule_id, severity, confidence, None, file, line, title, None, None)


def _run(engine, *findings, status="ok", error=None, warnings=(), version="v", own=None, duration=1.0):
    return EngineRun(engine, status, version, duration_sec=duration, error=error, own_verdict=own,
                     findings=list(findings), warnings=list(warnings))


def _runs(cisco=(), skillspector=(), manifest=(), cisco_status="ok", cisco_error=None, skillspector_status="ok"):
    return {
        "cisco": _run("cisco", *cisco, status=cisco_status, error=cisco_error),
        "skillspector": _run("skillspector", *skillspector, status=skillspector_status),
        "manifest": _run("manifest", *manifest),
    }


# --- вердикт по скиллу (D-52) ------------------------------------------------------------


@pytest.mark.parametrize(
    "runs, verdict",
    [
        (_runs(), "pass"),
        (_runs(cisco=[_f("cisco", "medium")], skillspector=[_f("skillspector", "low")]), "pass"),
        (_runs(cisco=[_f("cisco", "high")]), "review"),
        (_runs(cisco=[_f("cisco", "critical")]), "review"),  # critical одного движка -- review
        (_runs(cisco=[_f("cisco", "critical")], skillspector=[_f("skillspector", "high")]), "review"),
        (_runs(cisco=[_f("cisco", "critical")], skillspector=[_f("skillspector", "critical")]), "block"),
        (_runs(cisco=[_f("cisco", "high", rule_id="YARA_skills_shell_rc_persistence")]), "block"),
        (_runs(skillspector=[_f("skillspector", "high", rule_id="YARA_skills_x")]), "block"),
        (_runs(skillspector=[_f("skillspector", "high", rule_id="YARA_backdoor_persistence")]), "review"),
        (_runs(skillspector=[_f("skillspector", "medium", rule_id="YARA_skills_x")]), "pass"),
        (_runs(manifest=[_f("manifest", "high", rule_id="MANIFEST_HOOKS_COMMAND")]), "block"),
        (_runs(manifest=[_f("manifest", "medium", rule_id="MANIFEST_ALLOWED_TOOLS_BASH")]), "pass"),
    ],
)
def test_skill_verdict(runs, verdict):
    assert report.skill_verdict(runs)[0] == verdict


def test_confidence_ignored():
    runs = _runs(skillspector=[_f("skillspector", "high", confidence=0.1)])
    assert report.skill_verdict(runs)[0] == "review"


def test_block_reasons():
    runs = _runs(
        cisco=[_f("cisco", "critical"), _f("cisco", "high", rule_id="YARA_skills_a", title="Своё правило")],
        skillspector=[_f("skillspector", "critical"), _f("skillspector", "high", rule_id="YARA_skills_a", title="Своё правило")],
        manifest=[_f("manifest", "high", title="hooks")],
    )
    assert report.skill_verdict(runs) == (
        "block",
        [
            "Cisco skill-scanner: Своё правило",
            "NVIDIA SkillSpector: Своё правило",
            "Проверка frontmatter: hooks",
            "critical подтверждён обоими движками",
        ],
    )


def test_review_reason():
    runs = _runs(cisco=[_f("cisco", "critical"), _f("cisco", "high")], skillspector=[_f("skillspector", "high")])
    assert report.skill_verdict(runs) == (
        "review", ["1 critical, 2 high от: Cisco skill-scanner, NVIDIA SkillSpector — нужна ручная проверка"]
    )


def test_failed_engine_findings_ignored_and_no_confirmation():
    """Упавший движок не подтверждает critical: без второго мнения -- review."""
    runs = _runs(cisco=[_f("cisco", "critical")], skillspector=[_f("skillspector", "critical")], skillspector_status="failed")
    assert report.skill_verdict(runs)[0] == "review"


def test_single_engine_selected_cannot_confirm():
    runs = {"cisco": _run("cisco", _f("cisco", "critical")), "manifest": _run("manifest")}
    assert report.skill_verdict(runs)[0] == "review"


def test_worst():
    assert report.worst(["pass", "block", "review"]) == "block"
    assert report.worst(["pass", "review"]) == "review"
    assert report.worst([]) == "pass"


# --- отчёт целиком ------------------------------------------------------------------------


def _ctx(tmp_path, skills_runs: dict, engines=("cisco", "skillspector"), source_meta=None):
    ctx = ScanContext(
        scan_id=1, scan={}, config={}, engines=list(engines), source={"kind": "zip"}, workdir=tmp_path,
        deadline=Deadline(60), engine_timeout=30, max_skills=50, log=lambda *a, **k: None,
    )
    ctx.source_meta = source_meta or {
        "kind": "zip", "asset_id": 7, "filename": "pack.zip", "sha256": "ab" * 32, "size_bytes": 123
    }
    ctx.skills = [{"name": name, "path": f"skills/{name}", "dir": tmp_path / name} for name in skills_runs]
    ctx.engine_runs = {f"skills/{name}": runs for name, runs in skills_runs.items()}
    return ctx


def test_build_results_shape(tmp_path):
    ctx = _ctx(
        tmp_path,
        {
            "alpha": _runs(
                cisco=[_f("cisco", "medium", file="b.py", line=5), _f("cisco", "high", file="z.py")],
                skillspector=[_f("skillspector", "high", file="a.py", confidence=0.9)],
            ),
            "beta": _runs(manifest=[_f("manifest", "high", rule_id="MANIFEST_SHELL_INJECTION", file="SKILL.md")]),
            "gamma": _runs(),
        },
    )
    results = report.build_results(ctx)
    json.dumps(results)  # сериализуется в Scan.results
    assert results["engine"] == "skills-scanner"
    assert results["archive"] == {"id": 7, "filename": "pack.zip", "sha256": "ab" * 32, "size_bytes": 123}
    assert results["source"]["kind"] == "zip"
    assert results["verdict"] == "block"
    assert results["verdict_counts"] == {"pass": 1, "review": 1, "block": 1}
    assert results["complete"] is True and results["rejected"] is None
    assert results["llm"] == {"enabled": False}
    assert results["summary"] == {"critical": 0, "high": 3, "medium": 1, "low": 0, "info": 0, "total": 4}
    assert list(results["engines"]) == ["cisco", "skillspector", "manifest"]
    assert results["engines"]["cisco"] == {
        "label": "Cisco skill-scanner", "version": "v", "status": "ok", "duration_sec": 3.0, "llm": False,
        "error": None, "skills_failed": 0,
    }
    alpha, beta, gamma = results["skills"]
    assert (alpha["verdict"], beta["verdict"], gamma["verdict"]) == ("review", "block", "pass")
    assert beta["verdict_reasons"] == ["Проверка frontmatter: t"]
    assert gamma["verdict_reasons"] == [] and gamma["findings"] == []
    assert results["findings_truncated"] is False and alpha["findings_omitted"] == 0
    # Находки движков не склеиваются; порядок -- severity, файл, строка (D-14).
    assert [(f["engine"], f["severity"], f["file"]) for f in alpha["findings"]] == [
        ("skillspector", "high", "a.py"), ("cisco", "high", "z.py"), ("cisco", "medium", "b.py")
    ]
    assert alpha["findings"][0]["confidence"] == 0.9
    assert set(alpha["findings"][0]) == {
        "engine", "rule_id", "severity", "confidence", "category", "file", "line", "title", "finding", "fix", "snippet"
    }
    assert alpha["engines"]["cisco"] == {
        "status": "ok", "own_verdict": None, "duration_sec": 1.0, "findings": 2, "error": None, "warnings": []
    }


def test_partial_engine_failure(tmp_path):
    ctx = _ctx(
        tmp_path,
        {
            "alpha": _runs(cisco_error="код возврата 2", cisco_status="failed", skillspector=[_f("skillspector", "high")]),
            "beta": _runs(),
        },
    )
    results = report.build_results(ctx)
    assert results["complete"] is False
    assert results["skills"][0]["complete"] is False and results["skills"][1]["complete"] is True
    assert results["engines"]["cisco"]["status"] == "partial"
    assert results["engines"]["cisco"]["error"] == "код возврата 2"
    assert results["engines"]["cisco"]["skills_failed"] == 1
    assert results["verdict"] == "review"
    assert report.final_message(results) == (
        "Анализ навыков завершён, вердикт review (нужна ручная проверка); скиллов — review: 1, pass: 1; "
        "проверка неполная: не все движки отработали"
    )


@pytest.mark.parametrize(
    "statuses, expected",
    [(["failed", "failed"], "failed"), (["timeout", "timeout"], "timeout"), (["timeout", "failed"], "failed")],
)
def test_engine_total_status(statuses, expected):
    runs = [_run("cisco", status=s, error=s) for s in statuses]
    assert report._engine_total("cisco", runs)["status"] == expected


def test_only_selected_engines_in_report(tmp_path):
    runs = {"skillspector": _run("skillspector"), "manifest": _run("manifest")}
    results = report.build_results(_ctx(tmp_path, {"a": runs}, engines=("skillspector",)))
    assert list(results["engines"]) == ["skillspector", "manifest"]


def test_scan_wide_warnings_once(tmp_path):
    def runs():
        return {
            "cisco": _run("cisco"),
            "skillspector": _run("skillspector", warnings=[OSV_WARNING, "SkillSpector выполнил анализ не полностью"]),
            "manifest": _run("manifest"),
        }

    results = report.build_results(_ctx(tmp_path, {"a": runs(), "b": runs()}))
    assert results["warnings"] == [OSV_WARNING]
    assert results["skills"][0]["engines"]["skillspector"]["warnings"] == [
        OSV_WARNING, "SkillSpector выполнил анализ не полностью"
    ]


def test_repository_source_has_no_archive(tmp_path):
    meta = {"kind": "repository", "git_repo_url": "https://h.invalid/r", "git_ref": "main", "commit": "c" * 40}
    results = report.build_results(_ctx(tmp_path, {"a": _runs()}, source_meta=meta))
    assert results["source"] == meta and "archive" not in results


def test_final_message_pass(tmp_path):
    results = report.build_results(_ctx(tmp_path, {"a": _runs()}))
    assert report.final_message(results) == "Анализ навыков завершён, вердикт pass (находок high и выше нет); скиллов — pass: 1"


def test_real_reports_verdicts(tmp_path):
    """На настоящих отчётах движков (фикстуры) -- вердикт по D-52."""
    from app import engines

    def parsed(engine, fixture):
        run = EngineRun(engine, "ok", engines.get(engine).version)
        engines.get(engine).parse(json.loads((FIXTURES / fixture).read_text()), tmp_path, run)
        return run

    secrets = {"cisco": parsed("cisco", "cisco-environment-secrets.json"),
               "skillspector": parsed("skillspector", "skillspector-environment-secrets.json")}
    persistence = {"cisco": parsed("cisco", "cisco-shell-persistence-rules.json"),
                   "skillspector": parsed("skillspector", "skillspector-shell-persistence-rules.json")}
    assert report.skill_verdict(secrets)[0] == "review"
    verdict, reasons = report.skill_verdict(persistence)
    assert verdict == "block"
    assert "Cisco skill-scanner: Script appends to a shell startup file (persistence)" in reasons


def test_findings_truncated_keep_most_severe(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "MAX_REPORT_FINDINGS", 3)
    ctx = _ctx(
        tmp_path,
        {
            "a": _runs(cisco=[_f("cisco", "low"), _f("cisco", "high"), _f("cisco", "info")]),
            "b": _runs(skillspector=[_f("skillspector", "critical"), _f("skillspector", "medium")]),
        },
    )
    results = report.build_results(ctx)
    assert results["findings_truncated"] is True
    a, b = results["skills"]
    assert [f["severity"] for f in a["findings"]] == ["high"] and a["findings_omitted"] == 2
    assert [f["severity"] for f in b["findings"]] == ["critical", "medium"] and b["findings_omitted"] == 0
    # Сводки и вердикт -- по всем находкам.
    assert results["summary"]["total"] == 5 and a["summary"]["total"] == 3
