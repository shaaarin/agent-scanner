"""Оркестрация скана: фазы, ошибки, очередь, общий таймаут, прерванные сканы
(D-05, D-27, D-33, D-37, D-46). Этапы подменяются, чтобы проверять саму
оркестрацию; этапы целиком -- в test_sources/test_analysis/test_report."""
import json
import threading
import time

import pytest

from app import runner, stages
from app.context import ScanContext

from conftest import ZIP_SOURCE, make_zip, skill_md, zip_source

REPO_SOURCE = {
    "kind": "repository",
    "git_repo_url": "https://git.example.invalid/org/skills.git",
    "git_ref": "v1",
    "git_access_token": "secret-token",
}


def _wait(predicate, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def ok_stages(monkeypatch):
    """Этапы, которые проходят и отдают минимальный отчёт; запоминают ctx."""
    seen: dict = {}

    def fetch(ctx: ScanContext):
        seen["ctx"] = ctx
        seen["workdir_existed"] = ctx.workdir.is_dir()

    def build(ctx: ScanContext):
        return {"engine": "skills-scanner", "verdict": "pass", "engines_requested": ctx.engines}

    monkeypatch.setattr(stages, "fetch_sources", fetch)
    monkeypatch.setattr(stages, "analyze", lambda ctx: None)
    monkeypatch.setattr(stages, "build_results", build)
    return seen


# --- разбор конфига ----------------------------------------------------------------


@pytest.mark.parametrize("raw", [None, "", []])
def test_engines_default_both(raw):
    config = {} if raw is None else {"engines": raw}
    assert runner.parse_engines(config) == ["cisco", "skillspector"]


def test_engines_order_and_dedupe():
    assert runner.parse_engines({"engines": ["skillspector", "cisco", "cisco"]}) == ["cisco", "skillspector"]
    assert runner.parse_engines({"engines": "skillspector"}) == ["skillspector"]


def test_engines_unknown_rejected():
    with pytest.raises(RuntimeError, match="неизвестные движки: semgrep"):
        runner.parse_engines({"engines": ["cisco", "semgrep"]})
    with pytest.raises(RuntimeError, match="списком"):
        runner.parse_engines({"engines": {"cisco": True}})


@pytest.mark.parametrize(
    "source",
    [
        None,
        "zip",
        {"kind": "bundle"},
        {"kind": "zip", "asset_id": 1},
        {"kind": "zip", "archive_sha256": "ab"},
        {"kind": "repository", "git_repo_url": "  "},
    ],
)
def test_source_invalid(source):
    with pytest.raises(RuntimeError, match="создайте сканирование заново"):
        runner.parse_source({"source": source} if source is not None else {})


def test_source_valid():
    assert runner.parse_source({"source": ZIP_SOURCE}) == ZIP_SOURCE
    assert runner.parse_source({"source": REPO_SOURCE}) == REPO_SOURCE


def test_describe_source_hides_token():
    text = runner.describe_source(REPO_SOURCE)
    assert "secret-token" not in text
    assert "git.example.invalid" in text and "v1" in text
    assert "pack.zip" in runner.describe_source(ZIP_SOURCE)


# --- прогон скана ----------------------------------------------------------------------


def test_engines_missing_fails_honestly(api, monkeypatch, tmp_path):
    """Вне образа движков нет: скан не делает вид, что всё чисто."""
    monkeypatch.setenv("CISCO_BIN", str(tmp_path / "no-cisco"))
    monkeypatch.setenv("SKILLSPECTOR_BIN", str(tmp_path / "no-skillspector"))
    content = make_zip({"demo/SKILL.md": skill_md("demo")})
    api.archives[1] = content
    api.add_scan(1, config=json.dumps({"source": zip_source(content)}))
    runner.run_scan(1)
    scan = api.scans[1]
    assert scan["status"] == "failed"
    assert scan["phase"] == "Ошибка"
    assert scan["error"].startswith("Ни один движок не отработал: Cisco skill-scanner: не удалось запустить")
    assert json.loads(scan["results"]) == {"error": scan["error"]}
    assert scan["finished_at"]
    assert api.phases(1) == ["Инициализация", "Получение исходников", "Статический анализ", "Ошибка"]
    assert any(m.startswith("Найдено скиллов: 1: demo (demo)") for m in api.messages(1))
    assert not runner.is_running(1)


def test_completed_path(api, ok_stages):
    api.add_scan(2, config=json.dumps({"engines": ["skillspector"], "source": REPO_SOURCE}))
    runner.run_scan(2)
    scan = api.scans[2]
    assert scan["status"] == "completed", scan["error"]
    assert scan["phase"] == "Завершено"
    assert scan["error"] is None
    assert json.loads(scan["results"]) == {
        "engine": "skills-scanner",
        "verdict": "pass",
        "engines_requested": ["skillspector"],
    }
    assert api.phases(2) == [
        "Инициализация",
        "Получение исходников",
        "Статический анализ",
        "Сохранение результатов",
        "Завершено",
    ]
    # Последняя строка журнала пишется до смены статуса на completed.
    last_two = api.events[-2:]
    assert last_two[0][0] == "log" and last_two[0][2]["message"].startswith("Анализ навыков завершён, вердикт pass")
    assert last_two[1][0] == "patch" and last_two[1][2]["status"] == "completed"
    # Токен не попадает в журнал.
    assert not any("secret-token" in m for m in api.messages(2))


def test_context_and_workdir_cleanup(api, ok_stages):
    api.add_scan(3)
    runner.run_scan(3)
    ctx = ok_stages["ctx"]
    assert ok_stages["workdir_existed"]
    assert not ctx.workdir.exists()
    assert ctx.engines == ["cisco", "skillspector"]
    assert ctx.source == ZIP_SOURCE
    assert ctx.engine_timeout == runner.ENGINE_TIMEOUT
    assert ctx.max_skills == runner.MAX_SKILLS
    assert 0 < ctx.deadline.remaining() <= runner.TOTAL_TIMEOUT


def test_workdir_removed_on_failure(api, monkeypatch):
    seen = {}

    def fetch(ctx):
        seen["workdir"] = ctx.workdir
        (ctx.workdir / "junk").write_text("x")
        raise RuntimeError("архив повреждён")

    monkeypatch.setattr(stages, "fetch_sources", fetch)
    api.add_scan(4)
    runner.run_scan(4)
    assert api.scans[4]["error"] == "архив повреждён"
    assert not seen["workdir"].exists()


def test_wrong_scan_type_fails(api):
    api.add_scan(5, type="ai_code_scan")
    runner.run_scan(5)
    assert api.scans[5]["status"] == "failed"
    assert "только сканы типа agent_skills" in api.scans[5]["error"]


def test_wrong_asset_kind_fails(api):
    api.add_scan(6, asset_kind="agent")
    runner.run_scan(6)
    assert "а не на skill" in api.scans[6]["error"]


def test_missing_source_fails(api):
    api.add_scan(7, config="{}")
    runner.run_scan(7)
    assert "нет источника скиллов" in api.scans[7]["error"]


def test_bad_config_json_fails(api):
    api.add_scan(8, config="{not json")
    runner.run_scan(8)
    assert api.scans[8]["error"].startswith("конфиг скана не является JSON")


def test_unknown_engine_fails(api):
    api.add_scan(9, config=json.dumps({"engines": ["nope"], "source": ZIP_SOURCE}))
    runner.run_scan(9)
    assert "неизвестные движки: nope" in api.scans[9]["error"]


def test_llm_model_ignored_with_warning(api, ok_stages):
    api.add_scan(10, config=json.dumps({"eval_llm_model_id": 3, "source": ZIP_SOURCE}))
    runner.run_scan(10)
    assert api.scans[10]["status"] == "completed"
    assert any("LLM-анализ отключён" in m for m in api.messages(10))


def test_unexpected_error_reported_with_type(api, monkeypatch):
    def boom(ctx):
        raise KeyError("x")

    monkeypatch.setattr(stages, "fetch_sources", boom)
    api.add_scan(11)
    runner.run_scan(11)
    assert api.scans[11]["error"] == "KeyError: 'x'"


def test_scan_missing_in_control_api(api):
    # Скана нет: даже пометить failed некуда -- поток не должен упасть.
    runner.run_scan(404)
    assert not runner.is_running(404)


def test_total_timeout_fails_scan(api, monkeypatch):
    monkeypatch.setattr(runner, "TOTAL_TIMEOUT", 0.3)
    monkeypatch.setattr(stages, "fetch_sources", lambda ctx: time.sleep(0.5))
    api.add_scan(12)
    runner.run_scan(12)
    assert api.scans[12]["status"] == "failed"
    assert api.scans[12]["error"].startswith("Превышено общее время скана")
    assert "Статический анализ" not in api.phases(12)


# --- очередь и повторный запуск ------------------------------------------------------------


def test_queue_limits_concurrency(api, monkeypatch, ok_stages):
    monkeypatch.setattr(runner, "_slots", threading.BoundedSemaphore(1))
    release = threading.Event()
    inside = []

    def fetch(ctx):
        inside.append(ctx.scan_id)
        if ctx.scan_id == 20:
            assert release.wait(10)

    monkeypatch.setattr(stages, "fetch_sources", fetch)
    api.add_scan(20)
    api.add_scan(21)
    assert runner.start_in_background(20)
    assert _wait(lambda: inside == [20])
    assert runner.start_in_background(21)
    assert _wait(lambda: api.scans[21]["phase"] == "В очереди")
    time.sleep(0.2)
    assert inside == [20], "второй скан не должен стартовать, пока занят слот"
    assert any("ждём своей очереди" in m for m in api.messages(21))
    release.set()
    assert _wait(lambda: api.scans[21]["status"] == "completed")
    assert api.scans[20]["status"] == "completed"
    assert inside == [20, 21]
    assert api.phases(21)[0] == "В очереди"


def test_slot_released_after_failure(api, monkeypatch):
    monkeypatch.setattr(runner, "_slots", threading.BoundedSemaphore(1))
    api.add_scan(30)
    api.add_scan(31)
    runner.run_scan(30)
    runner.run_scan(31)  # не зависнет: слот вернулся после failed
    assert api.scans[31]["status"] == "failed"
    assert "В очереди" not in api.phases(31)


def test_duplicate_start_ignored(api, monkeypatch, ok_stages):
    release = threading.Event()
    monkeypatch.setattr(stages, "fetch_sources", lambda ctx: release.wait(10))
    api.add_scan(40)
    assert runner.start_in_background(40) is True
    assert runner.start_in_background(40) is False
    runner.run_scan(40)  # синхронный повтор тоже ничего не делает
    release.set()
    assert _wait(lambda: api.scans[40]["status"] == "completed")
    assert api.phases(40).count("Инициализация") == 1
    assert _wait(lambda: not runner.is_running(40))


# --- прерванные сканы --------------------------------------------------------------------------


def test_fail_interrupted_scans(api):
    api.add_scan(50)  # running, но не выполняется в этом процессе
    api.add_scan(51, status="completed")
    api.add_scan(52, type="ai_code_scan")  # чужой тип не трогаем
    runner._running.add(53)
    api.add_scan(53)  # выполняется здесь -- не трогаем
    runner.fail_interrupted_scans()
    assert api.scans[50]["status"] == "failed"
    assert "перезапущен" in api.scans[50]["error"]
    assert api.scans[51]["status"] == "completed"
    assert api.scans[52]["status"] == "running"
    assert api.scans[53]["status"] == "running"


def test_fail_interrupted_scans_control_api_down(monkeypatch):
    import httpx

    from app import control_client

    monkeypatch.setattr(control_client, "_client", httpx.Client(base_url="http://127.0.0.1:9", timeout=1))
    runner.fail_interrupted_scans()  # не бросает
