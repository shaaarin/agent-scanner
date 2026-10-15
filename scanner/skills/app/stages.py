"""Этапы скана, которые наполняются следующими подзадачами SKILLSS.md §4:

    fetch_sources -- подзадача 5 (готово, app/sources.py): zip из control-api
                     или git-клон, безопасная распаковка, поиск SKILL.md;
    analyze       -- подзадача 6 (готово, app/analysis.py + app/engines/):
                     движки по каждому скиллу; подзадача 7 -- свои правила
                     и мини-проверка frontmatter;
    build_results -- подзадача 8: единый отчёт и вердикт (§2.7).

Пока этап не реализован, он честно останавливает скан с понятным текстом:
никаких «пустых» результатов, которые выглядели бы как «чисто».
"""
from app import analysis, sources
from app.context import ScanContext


class StageNotImplemented(RuntimeError):
    """Этап ещё не реализован в этой версии сканера."""


def fetch_sources(ctx: ScanContext) -> None:
    sources.fetch(ctx)


def analyze(ctx: ScanContext) -> None:
    analysis.analyze(ctx)


def build_results(ctx: ScanContext) -> dict:
    raise StageNotImplemented("Сборка отчёта ещё не реализована в этой версии scanner-skills")
