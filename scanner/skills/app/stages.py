"""Этапы скана, которые вызывает runner:

    fetch_sources -- app/sources.py: zip из control-api или git-клон,
                     безопасная распаковка, поиск SKILL.md (D-49);
    analyze       -- app/analysis.py + app/engines/ + app/manifest_check.py:
                     движки и проверка frontmatter по каждому скиллу (D-50, D-51);
    build_results -- app/report.py: единый отчёт и вердикт (§2.7, D-52).

Отдельный модуль -- точка подмены этапов в тестах runner'а.
"""
from app import analysis, report, sources
from app.context import ScanContext


def fetch_sources(ctx: ScanContext) -> None:
    sources.fetch(ctx)


def analyze(ctx: ScanContext) -> None:
    analysis.analyze(ctx)


def build_results(ctx: ScanContext) -> dict:
    return report.build_results(ctx)
