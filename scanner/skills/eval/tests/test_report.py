"""Сводка, отчёт и сравнение с baseline — на искусственных результатах."""
from run_eval import diff_baseline, render_report, summarize, to_baseline


def _row(label, tech, cisco=None, ss=None, ok=True):
    def eng(sev):
        det = sev in ("HIGH", "CRITICAL")
        return {"ok": ok, "error": None if ok else "boom", "max_severity": sev, "detected": det and ok, "own_verdict": None, "rules": []}
    return {"label": label, "technique": tech, "source": "t", "cisco": eng(cisco), "skillspector": eng(ss)}


RESULTS = {
    "m1": _row("malicious", "exfil", cisco="HIGH", ss=None),
    "m2": _row("malicious", "exfil", cisco=None, ss="CRITICAL"),
    "m3": _row("malicious", "hooks", cisco=None, ss=None),
    "b1": _row("benign", "legit", cisco="MEDIUM", ss="HIGH"),
    "b2": _row("benign", "legit"),
    "c1": _row("contextual", "ctx", cisco="HIGH", ss="HIGH"),
}


def test_summarize_counts():
    s = summarize(RESULTS)
    assert s["malicious"]["n"] == 3 and s["malicious"]["hits"] == {"cisco": 1, "skillspector": 1}
    assert s["malicious"]["any"] == 2
    assert s["missed_by_all"] == ["m3"]
    assert s["benign"]["n"] == 2 and s["benign"]["false_positives"] == {"cisco": 0, "skillspector": 1}
    assert s["false_positives"] == {"skillspector": ["b1"]}
    assert s["by_technique"]["exfil"] == {"n": 2, "cisco": 1, "skillspector": 1, "any": 2}
    assert s["by_technique"]["hooks"]["any"] == 0


def test_contextual_cases_are_not_scored():
    s = summarize(RESULTS)
    assert s["malicious"]["n"] + s["benign"]["n"] == 5  # c1 не учитывается


def test_report_contains_table_and_gaps():
    text = render_report(summarize(RESULTS), {"cisco": "2.1.0"})
    assert "| exfil | 2 | 1 | 1 | 2 |" in text
    assert "- m3" in text
    assert "- skillspector: b1" in text
    assert "cisco: 2.1.0" in text


def test_errors_reported():
    res = {"x": _row("malicious", "t", cisco="HIGH", ss=None, ok=False)}
    s = summarize(res)
    assert len(s["errors"]) == 2 and s["malicious"]["hits"]["cisco"] == 0
    assert "Ошибки запуска" in render_report(s)


def test_baseline_roundtrip_and_diff():
    base = to_baseline(RESULTS)
    assert base["m1"] == {"cisco": "HIGH", "skillspector": None}
    assert diff_baseline(base, base) == []
    changed = {**base, "m3": {"cisco": "HIGH", "skillspector": None}}
    d = diff_baseline(changed, base)
    assert d == ["m3/cisco: было None, стало HIGH"]
    assert diff_baseline({k: v for k, v in base.items() if k != "m1"}, base) == ["m1: нет в текущем прогоне"]
    assert diff_baseline({**base, "new": base["m1"]}, base) == ["new: нет в baseline"]


def test_failed_engine_recorded_as_error_in_baseline():
    assert to_baseline({"x": _row("malicious", "t", ok=False)})["x"] == {"cisco": "ERROR", "skillspector": "ERROR"}
