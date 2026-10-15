"""Формат `Scan.results` для agent_skills (§2.7, D-36).

Пока здесь только результат для архива, отклонённого при распаковке (D-21):
он полностью задан §2.7 и не зависит от движков. Полный отчёт с находками и
вердиктом -- подзадача 8.
"""
from app.context import ScanContext

SEVERITIES = ("critical", "high", "medium", "low", "info")


def empty_summary() -> dict:
    return {**{severity: 0 for severity in SEVERITIES}, "total": 0}


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
        "engines": {},
        "skills": [],
    }
