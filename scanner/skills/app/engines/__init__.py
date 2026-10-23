"""Адаптеры движков (подзадача 6). Порядок -- как в `runner.ENGINES`."""
from app.engines.base import Engine, EngineRun, Finding
from app.engines.cisco import CiscoEngine
from app.engines.skillspector import SkillSpectorEngine

ENGINES: dict[str, Engine] = {engine.name: engine for engine in (CiscoEngine(), SkillSpectorEngine())}


def get(name: str) -> Engine:
    return ENGINES[name]


__all__ = ["ENGINES", "Engine", "EngineRun", "Finding", "get"]
