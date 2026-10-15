"""Этапы скана, которые наполняются следующими подзадачами SKILLSS.md §4:

    fetch_sources -- подзадача 5 (готово, app/sources.py): zip из control-api
                     или git-клон, безопасная распаковка, поиск SKILL.md;
    analyze       -- подзадачи 6-7: движки и мини-проверка frontmatter;
    build_results -- подзадача 8: единый отчёт и вердикт (§2.7).

Пока этап не реализован, он честно останавливает скан с понятным текстом:
никаких «пустых» результатов, которые выглядели бы как «чисто».
"""
from app import sources
from app.context import ScanContext


class StageNotImplemented(RuntimeError):
    """Этап ещё не реализован в этой версии сканера."""


def fetch_sources(ctx: ScanContext) -> None:
    sources.fetch(ctx)


def analyze(ctx: ScanContext) -> None:
    raise StageNotImplemented("Статический анализ ещё не реализован в этой версии scanner-skills")


def build_results(ctx: ScanContext) -> dict:
    raise StageNotImplemented("Сборка отчёта ещё не реализована в этой версии scanner-skills")
