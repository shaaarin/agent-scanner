"""Этап «Статический анализ»: каждый скилл -- выбранными движками (D-11).

Движки одного скилла работают параллельно (каждый -- свой процесс), скиллы
-- по очереди: так на скан не больше двух тяжёлых процессов (D-27). Таймаут
запуска -- min(SCAN_ENGINE_TIMEOUT, остаток дедлайна), между скиллами
проверяется общий дедлайн (D-33).

После движков по каждому скиллу всегда выполняется мини-проверка
frontmatter (`manifest_check`, D-31): в процессе сервиса, без подпроцесса.

Движок упал по скиллу -- это результат прогона, а не ошибка скана: отчёт
будет `complete: false` (D-23). Скан падает, только если не отработал ни
один запуск ни одного движка. Находки собираются в `ctx.engine_runs`,
отчёт и вердикт -- подзадача 8.
"""
from concurrent.futures import ThreadPoolExecutor

from app import engines, manifest_check
from app.context import ScanContext
from app.engines.base import EngineRun, SEVERITIES
from app.engines.skillspector import OSV_WARNING

# Предупреждения про окружение, а не про скилл: пишем один раз на скан.
SCAN_WIDE_WARNINGS = {OSV_WARNING}


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def label(engine: str) -> str:
    return manifest_check.LABEL if engine == manifest_check.ENGINE else engines.get(engine).label


def describe_run(run: EngineRun) -> str:
    label_text = label(run.engine)
    if not run.ok:
        return f"{label_text} не отработал: {run.error}"
    count = len(run.findings)
    text = f"{label_text} — {count} {_plural(count, 'находка', 'находки', 'находок')}"
    if run.findings:
        worst = min(run.findings, key=lambda f: SEVERITIES.index(f.severity)).severity
        text += f", макс. {worst}"
    return text + f", {run.duration_sec:.1f} с"


def _run_skill(ctx: ScanContext, index: int, skill: dict) -> dict[str, EngineRun]:
    timeout = ctx.deadline.engine_timeout(ctx.engine_timeout)
    base = ctx.workdir / "runs" / f"{index:03d}"

    def one(name: str) -> EngineRun:
        return engines.get(name).run(skill["dir"], workdir=base / name, timeout=timeout)

    with ThreadPoolExecutor(max_workers=len(ctx.engines), thread_name_prefix=f"skills-{ctx.scan_id}") as pool:
        results = list(pool.map(one, ctx.engines))
    runs = {run.engine: run for run in results}
    # Проверка frontmatter -- всегда, независимо от выбора движков (D-31, D-47).
    runs[manifest_check.ENGINE] = manifest_check.run(skill["dir"])
    return runs


def analyze(ctx: ScanContext) -> None:
    if not ctx.skills:
        raise RuntimeError("нет скиллов для анализа")
    total = len(ctx.skills)
    logged_warnings: set[str] = set()
    for index, skill in enumerate(ctx.skills, 1):
        ctx.deadline.check()
        runs = _run_skill(ctx, index, skill)
        ctx.engine_runs[skill["path"]] = runs
        failed = any(not run.ok for run in runs.values())
        ctx.log(
            f"[{index}/{total}] {skill['name']} ({skill['path']}): " + "; ".join(describe_run(r) for r in runs.values()),
            level="error" if failed else "info",
        )
        for run in runs.values():
            run_label = label(run.engine)
            for warning in run.warnings:
                if warning in SCAN_WIDE_WARNINGS:
                    if warning not in logged_warnings:
                        logged_warnings.add(warning)
                        ctx.log(f"{run_label}: {warning}")
                else:
                    ctx.log(f"[{index}/{total}] {skill['name']}: {run_label}: {warning}")
    ctx.deadline.check()

    all_runs = [run for runs in ctx.engine_runs.values() for run in runs.values()]
    # Скан держится на движках: одна проверка frontmatter -- не результат (D-23).
    engine_runs = [run for run in all_runs if run.engine != manifest_check.ENGINE]
    if not any(run.ok for run in engine_runs):
        errors = sorted({f"{label(r.engine)}: {r.error}" for r in engine_runs})
        raise RuntimeError("Ни один движок не отработал: " + "; ".join(errors[:4]))
    for name in ctx.engines:
        broken = sum(1 for runs in ctx.engine_runs.values() if not runs[name].ok)
        if broken:
            ctx.log(
                f"{engines.get(name).label} не отработал на {broken} из {total} скиллов — отчёт будет неполным",
                level="error",
            )
    findings = sum(len(run.findings) for run in all_runs)
    ctx.log(f"Статический анализ завершён: {findings} {_plural(findings, 'находка', 'находки', 'находок')}", level="success")
