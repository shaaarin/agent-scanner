"""Интеграционные проверки на реальных движках (пропускаются, если движков нет).

CISCO_BIN / SKILLSPECTOR_BIN — пути к бинарям из запиненных venv.
Полный прогон корпуса (~4 мин) включается переменной FULL_EVAL=1.
"""
import json
import os

import pytest

from corpus import load_manifest
from engines import run_cisco, run_skillspector
from run_eval import BASELINE, diff_baseline, run_all, summarize, to_baseline

pytestmark = pytest.mark.engines

CASES = {c.id: c for c in load_manifest()}


def test_known_gap_hooks_not_detected_by_either(cisco_bin, skillspector_bin):
    """Зафиксированный пробел: hooks с shell-командой не даёт HIGH ни у одного движка (закрывает правило D-31)."""
    case = CASES["marker/hooks-command"]
    assert not run_cisco(case.path, cisco_bin).detected()
    assert not run_skillspector(case.path, skillspector_bin).detected()


def test_known_gap_bang_injection_not_detected(cisco_bin, skillspector_bin):
    case = CASES["marker/bang-injection"]
    assert not run_cisco(case.path, cisco_bin).detected()
    assert not run_skillspector(case.path, skillspector_bin).detected()


def test_persistence_detected_by_skillspector_only(cisco_bin, skillspector_bin):
    case = CASES["marker/shell-persistence"]
    ss = run_skillspector(case.path, skillspector_bin)
    assert ss.detected() and ss.max_severity == "HIGH"
    assert not run_cisco(case.path, cisco_bin).detected()


def test_plain_benign_is_clean(cisco_bin, skillspector_bin):
    case = CASES["marker/benign-plain"]
    assert not run_cisco(case.path, cisco_bin).detected()
    assert not run_skillspector(case.path, skillspector_bin).detected()


def test_known_malicious_caught_by_cisco(cisco_bin):
    res = run_cisco(CASES["cisco/command-injection/eval-execution"].path, cisco_bin)
    assert res.ok and res.detected()
    assert any("COMMAND_INJECTION" in f.rule_id for f in res.findings)


def test_engines_run_on_nonexistent_dir_does_not_crash(cisco_bin, skillspector_bin, tmp_path):
    for fn, b in ((run_cisco, cisco_bin), (run_skillspector, skillspector_bin)):
        res = fn(tmp_path / "nope", b)
        assert not res.detected()  # ошибка или пусто, но не исключение и не «поймал»


@pytest.mark.skipif(os.environ.get("FULL_EVAL") != "1", reason="полный прогон: FULL_EVAL=1")
def test_full_corpus_matches_baseline(cisco_bin, skillspector_bin):
    results = run_all(list(CASES.values()), cisco_bin, skillspector_bin)
    assert not summarize(results)["errors"]
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert diff_baseline(to_baseline(results), baseline) == []
