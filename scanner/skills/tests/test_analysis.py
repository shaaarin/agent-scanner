"""Этап «Статический анализ» (D-11, D-23, D-33): все скиллы выбранными
движками, частичный результат при падении одного движка, failed -- если не
отработал ни один, общий дедлайн."""
import json
import time

import pytest

from app import analysis, runner
from app.context import Deadline, ScanContext, ScanTimeout
from app.engines.base import Engine, EngineRun
from app.engines.skillspector import OSV_WARNING

from conftest import make_zip, skill_md, zip_source
from engine_fakes import fixture_body, install, install_fixture, offline_stderr


def _ctx(tmp_path, names=("alpha", "beta"), engines=("cisco", "skillspector"), deadline=600, engine_timeout=30):
    workdir = tmp_path / "work"
    skills = []
    for name in names:
        path = workdir / "src" / name
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text(skill_md(name))
        skills.append({"name": name, "path": name, "dir": path})
    logs = []
    ctx = ScanContext(
        scan_id=5,
        scan={},
        config={},
        engines=list(engines),
        source={"kind": "zip"},
        workdir=workdir,
        deadline=Deadline(deadline),
        engine_timeout=engine_timeout,
        max_skills=50,
        log=lambda message, **kw: logs.append((kw.get("level", "info"), message)),
    )
    ctx.skills = skills
    return ctx, logs


@pytest.fixture
def both_ok(tmp_path, monkeypatch):
    install_fixture(tmp_path, monkeypatch, "cisco", "cisco-environment-secrets.json")
    install_fixture(tmp_path, monkeypatch, "skillspector", "skillspector-environment-secrets.json")


def test_all_skills_all_engines(tmp_path, both_ok):
    ctx, logs = _ctx(tmp_path)
    analysis.analyze(ctx)
    assert list(ctx.engine_runs) == ["alpha", "beta"]
    for runs in ctx.engine_runs.values():
        assert list(runs) == ["cisco", "skillspector", "manifest"]
        assert all(run.ok for run in runs.values())
        assert runs["cisco"].findings[0].rule_id == "DATA_EXFIL_SENSITIVE_FILES"
    assert logs[0][0] == "info"
    assert logs[0][1].startswith("[1/2] alpha (alpha): Cisco skill-scanner — 1 находка, макс. high")
    assert "NVIDIA SkillSpector — 2 находки, макс. high" in logs[0][1]
    assert logs[-1] == ("success", "Статический анализ завершён: 6 находок")
    # У каждого запуска -- своя папка, отчёты не перетирают друг друга.
    assert (ctx.workdir / "runs" / "001" / "cisco" / "report.json").is_file()
    assert (ctx.workdir / "runs" / "002" / "skillspector" / "report.json").is_file()


def test_only_selected_engine(tmp_path, monkeypatch):
    install_fixture(tmp_path, monkeypatch, "skillspector", "skillspector-environment-secrets.json")
    monkeypatch.setenv("CISCO_BIN", str(tmp_path / "must-not-run"))
    ctx, _ = _ctx(tmp_path, names=("alpha",), engines=("skillspector",))
    analysis.analyze(ctx)
    assert list(ctx.engine_runs["alpha"]) == ["skillspector", "manifest"]


def test_engines_run_in_parallel(tmp_path, monkeypatch):
    body = "time.sleep(1)\n" + fixture_body("cisco-benign-plain.json")
    install(tmp_path, monkeypatch, "cisco", body)
    install(tmp_path, monkeypatch, "skillspector", "time.sleep(1)\n" + fixture_body("skillspector-unpinned-online.json"))
    ctx, _ = _ctx(tmp_path, names=("alpha",))
    started = time.monotonic()
    analysis.analyze(ctx)
    assert time.monotonic() - started < 1.9


def test_one_engine_fails_partial_result(tmp_path, monkeypatch):
    install_fixture(tmp_path, monkeypatch, "cisco", "cisco-environment-secrets.json")
    install(tmp_path, monkeypatch, "skillspector", "sys.stderr.write('boom\\n'); sys.exit(3)")
    ctx, logs = _ctx(tmp_path)
    analysis.analyze(ctx)
    assert ctx.engine_runs["alpha"]["skillspector"].status == "failed"
    assert ctx.engine_runs["alpha"]["cisco"].ok
    assert logs[0][0] == "error"
    assert "NVIDIA SkillSpector не отработал: код возврата 3: boom" in logs[0][1]
    assert ("error", "NVIDIA SkillSpector не отработал на 2 из 2 скиллов — отчёт будет неполным") in logs


def test_all_engines_fail(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch, "cisco", "sys.exit(1)")
    install(tmp_path, monkeypatch, "skillspector", "pass")
    ctx, _ = _ctx(tmp_path)
    with pytest.raises(RuntimeError, match="Ни один движок не отработал") as exc:
        analysis.analyze(ctx)
    assert "Cisco skill-scanner: код возврата 1" in str(exc.value)
    assert "NVIDIA SkillSpector: движок завершился без отчёта" in str(exc.value)


def test_osv_warning_logged_once(tmp_path, monkeypatch):
    install_fixture(tmp_path, monkeypatch, "cisco", "cisco-benign-plain.json")
    install_fixture(
        tmp_path, monkeypatch, "skillspector", "skillspector-unpinned-online.json", stderr=offline_stderr()
    )
    ctx, logs = _ctx(tmp_path, names=("a", "b", "c"))
    analysis.analyze(ctx)
    osv = [m for _, m in logs if OSV_WARNING in m]
    assert osv == [f"NVIDIA SkillSpector: {OSV_WARNING}"]
    assert all(OSV_WARNING in runs["skillspector"].warnings for runs in ctx.engine_runs.values())


def test_skill_warnings_logged_with_skill_name(tmp_path, monkeypatch):
    install_fixture(tmp_path, monkeypatch, "cisco", "cisco-benign-plain.json")
    install(
        tmp_path,
        monkeypatch,
        "skillspector",
        "output.write_text(json.dumps({'issues': [], 'analysis_completeness': {'is_complete': False}}))",
    )
    ctx, logs = _ctx(tmp_path)
    analysis.analyze(ctx)
    warnings = [m for _, m in logs if "не полностью" in m]
    assert warnings == [
        "[1/2] alpha: NVIDIA SkillSpector: SkillSpector выполнил анализ не полностью",
        "[2/2] beta: NVIDIA SkillSpector: SkillSpector выполнил анализ не полностью",
    ]


@pytest.mark.parametrize("deadline, per_engine, expected", [(600, 30, 30), (10, 300, 10)])
def test_engine_timeout_is_min_of_engine_and_deadline(tmp_path, monkeypatch, deadline, per_engine, expected):
    seen = []

    def fake_run(self, skill_dir, *, workdir, timeout, llm=None):
        seen.append(timeout)
        return EngineRun(self.name, "ok", self.version)

    monkeypatch.setattr(Engine, "run", fake_run)
    ctx, _ = _ctx(tmp_path, names=("alpha",), deadline=deadline, engine_timeout=per_engine)
    analysis.analyze(ctx)
    assert len(seen) == 2 and all(expected - 1 < t <= expected for t in seen)


def test_engine_killed_on_timeout(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch, "cisco", "time.sleep(30)")
    ctx, _ = _ctx(tmp_path, names=("alpha",), engines=("cisco",), engine_timeout=1)
    with pytest.raises(RuntimeError, match="превышен таймаут"):
        analysis.analyze(ctx)
    assert ctx.engine_runs["alpha"]["cisco"].status == "timeout"
    assert ctx.engine_runs["alpha"]["cisco"].duration_sec < 10


def test_total_deadline_stops_between_skills(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch, "cisco", "time.sleep(30)")
    ctx, _ = _ctx(tmp_path, names=("a", "b"), engines=("cisco",), deadline=0.6)
    with pytest.raises(ScanTimeout):
        analysis.analyze(ctx)
    assert list(ctx.engine_runs) == ["a"]  # до второго скилла не дошли


def test_no_skills(tmp_path):
    ctx, _ = _ctx(tmp_path, names=())
    with pytest.raises(RuntimeError, match="нет скиллов"):
        analysis.analyze(ctx)


@pytest.mark.parametrize("n, word", [(1, "находка"), (2, "находки"), (5, "находок"), (11, "находок"), (21, "находка"), (112, "находок")])
def test_plural(n, word):
    assert analysis._plural(n, "находка", "находки", "находок") == word


# --- через runner ---------------------------------------------------------------------------


def test_runner_completes_with_report(api, tmp_path, monkeypatch):
    install_fixture(tmp_path, monkeypatch, "cisco", "cisco-environment-secrets.json")
    install_fixture(tmp_path, monkeypatch, "skillspector", "skillspector-environment-secrets.json")
    content = make_zip({"pack/a/SKILL.md": skill_md("alpha")})
    api.archives[1] = content
    api.add_scan(80, config=json.dumps({"source": zip_source(content)}))
    runner.run_scan(80)
    scan = api.scans[80]
    assert scan["status"] == "completed", scan["error"]
    assert api.phases(80) == [
        "Инициализация", "Получение исходников", "Статический анализ", "Сохранение результатов", "Завершено"
    ]
    results = json.loads(scan["results"])
    # high у обоих движков, своих сигналов нет -- review (D-52).
    assert results["verdict"] == "review" and results["complete"] is True
    assert [s["name"] for s in results["skills"]] == ["alpha"]
    assert any(m.startswith("[1/1] alpha (pack/a): Cisco skill-scanner — 1 находка") for m in api.messages(80))
    assert api.messages(80)[-1] == "Анализ навыков завершён, вердикт review (нужна ручная проверка); скиллов — review: 1"


def test_runner_all_engines_failed(api, tmp_path, monkeypatch):
    install(tmp_path, monkeypatch, "cisco", "sys.exit(1)")
    content = make_zip({"a/SKILL.md": skill_md("a")})
    api.archives[1] = content
    api.add_scan(81, config=json.dumps({"source": zip_source(content), "engines": ["cisco"]}))
    runner.run_scan(81)
    assert api.scans[81]["status"] == "failed"
    assert api.scans[81]["error"].startswith("Ни один движок не отработал: Cisco skill-scanner: код возврата 1")
