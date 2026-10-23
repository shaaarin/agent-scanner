"""Формат `Scan.results` для agent_skills (§2.7, D-36) и вердикт (D-10, D-52).

Вердикт считаем сами; вердикты движков -- только справочно (`own_verdict`).
Правило D-52 (вариант «г» из R-31) по каждому скиллу:

    block  -- находка high+ от наших сигналов: свои YARA-правила (`YARA_skills_*`,
              в любом движке) или проверка frontmatter (`manifest`);
              или critical есть сразу у обоих движков (Cisco и SkillSpector);
    review -- любая другая находка critical/high;
    pass   -- иначе («находок high+ нет», а не «безопасен»).

Общий вердикт -- худший из скиллов (D-13); архив, отклонённый при распаковке
(D-21), -- block без скиллов. `complete: false`, если хоть один запуск движка
по хоть одному скиллу не `ok` (D-23). `confidence` в вердикте не участвует
(D-34). Находки двух движков не склеиваются (D-14).
"""
from app import manifest_check
from app.analysis import SCAN_WIDE_WARNINGS
from app.context import ScanContext
from app.engines import ENGINES
from app.engines.base import EngineRun, Finding, SEVERITIES, sort_key

VERDICTS = ("pass", "review", "block")  # по возрастанию
# Находок в Scan.results на весь скан (GET /scans отдаёт results целиком):
# остаются самые серьёзные, сводки и вердикт считаются по всем.
MAX_REPORT_FINDINGS = 2000
BLOCKING = ("critical", "high")
# rules/build_pack.py: имена своих правил начинаются с skills_, rule_id -- YARA_<имя>.
OWN_RULE_PREFIX = "YARA_skills_"
CONFIRMING_ENGINES = ("cisco", "skillspector")
LABELS = {**{name: engine.label for name, engine in ENGINES.items()}, manifest_check.ENGINE: manifest_check.LABEL}


def empty_summary() -> dict:
    return {**{severity: 0 for severity in SEVERITIES}, "total": 0}


def summarize(findings: list[Finding]) -> dict:
    summary = empty_summary()
    for finding in findings:
        summary[finding.severity] += 1
        summary["total"] += 1
    return summary


def worst(verdicts) -> str:
    return max(verdicts, key=VERDICTS.index, default="pass")


def is_own_signal(finding: Finding) -> bool:
    return finding.engine == manifest_check.ENGINE or finding.rule_id.startswith(OWN_RULE_PREFIX)


def skill_verdict(runs: dict[str, EngineRun]) -> tuple[str, list[str]]:
    """(вердикт, причины) для одного скилла по прогонам его движков."""
    findings = [f for run in runs.values() if run.ok for f in run.findings]
    reasons: list[str] = []

    own = [f for f in findings if is_own_signal(f) and f.severity in BLOCKING]
    for finding in own:
        reason = f"{LABELS.get(finding.engine, finding.engine)}: {finding.title}"
        if reason not in reasons:
            reasons.append(reason)
    critical_by = [
        name for name in CONFIRMING_ENGINES
        if name in runs and runs[name].ok and any(f.severity == "critical" for f in runs[name].findings)
    ]
    if len(critical_by) == len(CONFIRMING_ENGINES):
        reasons.append("critical подтверждён обоими движками")
    if reasons:
        return "block", reasons

    serious = [f for f in findings if f.severity in BLOCKING]
    if serious:
        engines = sorted({LABELS.get(f.engine, f.engine) for f in serious})
        counts = summarize(serious)
        text = ", ".join(f"{counts[s]} {s}" for s in BLOCKING if counts[s])
        return "review", [f"{text} от: {', '.join(engines)} — нужна ручная проверка"]
    return "pass", []


def _skill_engine(run: EngineRun) -> dict:
    return {
        "status": run.status,
        "own_verdict": run.own_verdict,
        "duration_sec": run.duration_sec,
        "findings": len(run.findings),
        "error": run.error,
        "warnings": list(run.warnings),
    }


def _engine_total(name: str, runs: list[EngineRun]) -> dict:
    """Сводка движка по всем скиллам: ok -- все запуски ok; failed/timeout --
    ни одного ok (timeout, если все неуспешные -- таймауты); partial -- часть."""
    bad = [run for run in runs if not run.ok]
    if not bad:
        status = "ok"
    elif len(bad) < len(runs):
        status = "partial"
    else:
        status = "timeout" if all(run.status == "timeout" for run in bad) else "failed"
    version = runs[0].version if runs else ""
    return {
        "label": LABELS.get(name, name),
        "version": version,
        "status": status,
        "duration_sec": round(sum(run.duration_sec for run in runs), 2),
        "llm": any(run.llm for run in runs),
        "error": bad[0].error if bad else None,
        "skills_failed": len(bad),
    }


def source_section(ctx: ScanContext) -> dict:
    """Что сканировали. Для zip -- ещё и `archive` в форме §2.7."""
    meta = ctx.source_meta or {"kind": ctx.source.get("kind")}
    section: dict = {"source": meta}
    if meta.get("kind") == "zip":
        section["archive"] = {
            "id": meta.get("asset_id"),
            "filename": meta.get("filename"),
            "sha256": meta.get("sha256"),
            "size_bytes": meta.get("size_bytes"),
        }
    return section


def build_results(ctx: ScanContext) -> dict:
    """Полный отчёт по результатам этапа анализа (`ctx.engine_runs`)."""
    skills = []
    per_engine: dict[str, list[EngineRun]] = {}
    all_findings: list[Finding] = []
    warnings: list[str] = []
    for skill in ctx.skills:
        runs = ctx.engine_runs.get(skill["path"], {})
        findings = sorted((f for run in runs.values() if run.ok for f in run.findings), key=sort_key)
        verdict, reasons = skill_verdict(runs)
        for name, run in runs.items():
            per_engine.setdefault(name, []).append(run)
            # Предупреждения про окружение (OSV.dev) -- на весь скан; про скилл
            # -- в его движке (`engines.<имя>.warnings`).
            warnings.extend(w for w in run.warnings if w in SCAN_WIDE_WARNINGS and w not in warnings)
        all_findings.extend(findings)
        skills.append(
            {
                "name": skill["name"],
                "path": skill["path"],
                "verdict": verdict,
                "verdict_reasons": reasons,
                "complete": all(run.ok for run in runs.values()),
                "summary": summarize(findings),
                "engines": {name: _skill_engine(run) for name, run in runs.items()},
                "findings": [finding.as_dict() for finding in findings],
            }
        )
    truncated = _truncate(skills)
    order = [name for name in (*ctx.engines, manifest_check.ENGINE) if name in per_engine]
    return {
        "engine": "skills-scanner",
        **source_section(ctx),
        "verdict": worst(skill["verdict"] for skill in skills),
        "complete": all(skill["complete"] for skill in skills),
        "rejected": None,
        "llm": {"enabled": False},
        "summary": summarize(all_findings),
        "verdict_counts": {v: sum(1 for s in skills if s["verdict"] == v) for v in VERDICTS},
        "engines": {name: _engine_total(name, per_engine[name]) for name in order},
        "warnings": warnings,
        "findings_truncated": truncated,
        "skills": skills,
    }


def _truncate(skills: list[dict]) -> bool:
    """Оставляет MAX_REPORT_FINDINGS самых серьёзных находок по всему скану;
    у скилла -- `findings_omitted`, сколько не попало в отчёт."""
    ranked = sorted(
        ((SEVERITIES.index(f["severity"]), i, j) for i, s in enumerate(skills) for j, f in enumerate(s["findings"])),
    )
    keep = {(i, j) for _, i, j in ranked[:MAX_REPORT_FINDINGS]}
    for i, skill in enumerate(skills):
        kept = [f for j, f in enumerate(skill["findings"]) if (i, j) in keep]
        skill["findings_omitted"] = len(skill["findings"]) - len(kept)
        skill["findings"] = kept
    return len(ranked) > MAX_REPORT_FINDINGS


VERDICT_TEXT = {"pass": "pass (находок high и выше нет)", "review": "review (нужна ручная проверка)", "block": "block"}


def final_message(results: dict) -> str:
    counts = results.get("verdict_counts") or {}
    by_skill = ", ".join(f"{v}: {counts[v]}" for v in reversed(VERDICTS) if counts.get(v))
    text = f"Анализ навыков завершён, вердикт {VERDICT_TEXT.get(results['verdict'], results['verdict'])}"
    if by_skill:
        text += f"; скиллов — {by_skill}"
    if not results.get("complete", True):
        text += "; проверка неполная: не все движки отработали"
    return text


def rejected_results(ctx: ScanContext) -> dict:
    """Архив отклонён: вердикт block, скиллов нет, движки не запускались."""
    return {
        "engine": "skills-scanner",
        **source_section(ctx),
        "verdict": "block",
        "complete": True,
        "rejected": dict(ctx.rejected),
        "llm": {"enabled": False},
        "summary": empty_summary(),
        "verdict_counts": {"pass": 0, "review": 0, "block": 0},
        "engines": {},
        "warnings": [],
        "findings_truncated": False,
        "skills": [],
    }
