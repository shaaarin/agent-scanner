"""Прогон корпуса через оба движка и таблица «техника -> кто поймал».

Примеры:
  python run_eval.py --cisco-bin /opt/engines/cisco/bin/skill-scanner \
      --skillspector-bin /opt/engines/skillspector/bin/skillspector
  python run_eval.py ... --update-baseline     # перезаписать baseline.json
  python run_eval.py ... --with-external       # + anthropics/skills (после fetch_external.sh)
  python run_eval.py ... --rules-dir ../rules  # свои правила (в образе берутся из $SKILLS_RULES_DIR)
Результаты: results/results.json и results/report.md (каталог в .gitignore).
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from corpus import EVAL_DIR, Case, external_cases, load_manifest
from engines import EngineResult, cisco_pack, run_cisco, run_skillspector, yara_dir

ENGINES = ("cisco", "skillspector")
BASELINE = EVAL_DIR / "baseline.json"
RESULTS_DIR = EVAL_DIR / "results"


def result_row(res: EngineResult) -> dict:
    return {
        "ok": res.ok,
        "error": res.error,
        "max_severity": res.max_severity,
        "detected": res.detected(),
        "own_verdict": res.own_verdict,
        "rules": sorted({f.rule_id for f in res.findings if f.severity in ("HIGH", "CRITICAL")}),
    }


def run_case(case: Case, cisco_bin: str, ss_bin: str, timeout: int, rules_dir: Path | None = None) -> dict:
    row = {"label": case.label, "technique": case.technique, "source": case.source}
    row["cisco"] = result_row(run_cisco(case.path, cisco_bin, timeout, rules_dir))
    row["skillspector"] = result_row(run_skillspector(case.path, ss_bin, timeout, rules_dir))
    return row


def run_all(
    cases: list[Case], cisco_bin: str, ss_bin: str, timeout: int = 300, workers: int = 2, rules_dir: Path | None = None
) -> dict:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(lambda c: run_case(c, cisco_bin, ss_bin, timeout, rules_dir), cases))
    return {c.id: r for c, r in zip(cases, rows)}


def summarize(results: dict) -> dict:
    """Сводка: recall по вредоносным, FP по безвредным, разбивка по техникам."""
    out = {"malicious": {"n": 0}, "benign": {"n": 0}, "by_technique": {}, "missed_by_all": [], "false_positives": defaultdict(list), "errors": []}
    by_tech = defaultdict(lambda: {"n": 0, "cisco": 0, "skillspector": 0, "any": 0})
    mal_hits = {e: 0 for e in ENGINES}
    mal_any = 0
    ben_fp = {e: 0 for e in ENGINES}
    for cid, row in results.items():
        for e in ENGINES:
            if not row[e]["ok"]:
                out["errors"].append(f"{cid}: {e}: {row[e]['error']}")
        if row["label"] == "malicious":
            out["malicious"]["n"] += 1
            t = by_tech[row["technique"]]
            t["n"] += 1
            hit_any = False
            for e in ENGINES:
                if row[e]["detected"]:
                    mal_hits[e] += 1
                    t[e] += 1
                    hit_any = True
            if hit_any:
                mal_any += 1
                t["any"] += 1
            else:
                out["missed_by_all"].append(cid)
        elif row["label"] == "benign":
            out["benign"]["n"] += 1
            for e in ENGINES:
                if row[e]["detected"]:
                    ben_fp[e] += 1
                    out["false_positives"][e].append(cid)
    out["malicious"].update(hits=mal_hits, any=mal_any)
    out["benign"]["false_positives"] = ben_fp
    out["by_technique"] = dict(sorted(by_tech.items()))
    out["false_positives"] = dict(out["false_positives"])
    return out


def render_report(summary: dict, engine_versions: dict[str, str] | None = None) -> str:
    m, b = summary["malicious"], summary["benign"]
    lines = ["# Сравнение движков на корпусе (только статика, без LLM)", ""]
    if engine_versions:
        lines += [f"- {k}: {v}" for k, v in engine_versions.items()] + [""]
    lines += [
        f"Порог «поймал»: severity HIGH и выше. Вредоносных: {m['n']}, безвредных: {b['n']}.",
        "",
        "| Движок | Поймал вредоносных | Ложных срабатываний на безвредных |",
        "|---|---|---|",
    ]
    for e in ENGINES:
        lines.append(f"| {e} | {m['hits'][e]}/{m['n']} | {b['false_positives'][e]}/{b['n']} |")
    lines.append(f"| объединение | {m['any']}/{m['n']} | — |")
    lines += ["", "## По техникам (вредоносные)", "", "| Техника | Кейсов | cisco | skillspector | хоть один |", "|---|---|---|---|---|"]
    for tech, t in summary["by_technique"].items():
        lines.append(f"| {tech} | {t['n']} | {t['cisco']} | {t['skillspector']} | {t['any']} |")
    lines += ["", "## Пропущены обоими", ""]
    lines += [f"- {c}" for c in summary["missed_by_all"]] or ["- нет"]
    lines += ["", "## Ложные срабатывания", ""]
    fps = [f"- {e}: {c}" for e, cs in summary["false_positives"].items() for c in cs]
    lines += fps or ["- нет"]
    if summary["errors"]:
        lines += ["", "## Ошибки запуска", ""] + [f"- {x}" for x in summary["errors"]]
    return "\n".join(lines) + "\n"


def to_baseline(results: dict) -> dict:
    return {
        cid: {e: (row[e]["max_severity"] if row[e]["ok"] else "ERROR") for e in ENGINES}
        for cid, row in sorted(results.items())
    }


def diff_baseline(current: dict, baseline: dict) -> list[str]:
    """Расхождения с зафиксированной базой: движки запинены, поэтому любой сдвиг — повод посмотреть."""
    diffs = []
    for cid in sorted(set(current) | set(baseline)):
        if cid not in baseline:
            diffs.append(f"{cid}: нет в baseline")
        elif cid not in current:
            diffs.append(f"{cid}: нет в текущем прогоне")
        else:
            for e in ENGINES:
                if current[cid][e] != baseline[cid][e]:
                    diffs.append(f"{cid}/{e}: было {baseline[cid][e]}, стало {current[cid][e]}")
    return diffs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cisco-bin", default="skill-scanner")
    ap.add_argument("--skillspector-bin", default="skillspector")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--with-external", action="store_true")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument(
        "--rules-dir",
        type=Path,
        default=os.environ.get("SKILLS_RULES_DIR"),
        help="свои правила (rules/ с собранным cisco-pack); в образе -- $SKILLS_RULES_DIR. baseline снят с ними",
    )
    args = ap.parse_args()
    if not (cisco_pack(args.rules_dir) and yara_dir(args.rules_dir)):
        print("ВНИМАНИЕ: свои правила не подключены (--rules-dir) -- результат не сравним с baseline")

    cases = load_manifest()
    if args.with_external:
        cases += external_cases()
    results = run_all(cases, args.cisco_bin, args.skillspector_bin, args.timeout, rules_dir=args.rules_dir)

    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    report = render_report(summarize(results))
    (RESULTS_DIR / "report.md").write_text(report, encoding="utf-8")
    print(report)

    base_cur = to_baseline({k: v for k, v in results.items() if not k.startswith("anthropic/")})
    if args.update_baseline:
        BASELINE.write_text(json.dumps(base_cur, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"baseline обновлён: {BASELINE.name}")
        return 0
    if BASELINE.exists():
        diffs = diff_baseline(base_cur, json.loads(BASELINE.read_text(encoding="utf-8")))
        if diffs:
            print("Расхождения с baseline:\n" + "\n".join(diffs))
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
