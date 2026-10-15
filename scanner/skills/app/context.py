"""Состояние одного скана, которое runner передаёт этапам, и общий дедлайн
скана (D-33)."""
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


class ScanTimeout(RuntimeError):
    """Превышено общее время скана (SCAN_TOTAL_TIMEOUT) -- скан failed."""


class Deadline:
    """Общий дедлайн скана. Этапы проверяют его между шагами (`check`), а
    таймаут подпроцесса движка берут как min(таймаут движка, `remaining`),
    так что ни один запуск не переживает скан."""

    def __init__(self, seconds: float, *, clock: Callable[[], float] = time.monotonic):
        self.seconds = seconds
        self._clock = clock
        self._end = clock() + seconds

    def remaining(self) -> float:
        return max(0.0, self._end - self._clock())

    def expired(self) -> bool:
        return self.remaining() <= 0

    def check(self) -> None:
        if self.expired():
            raise ScanTimeout(f"Превышено общее время скана ({self.seconds:.0f} с)")

    def engine_timeout(self, per_engine: float) -> float:
        return min(per_engine, self.remaining())


@dataclass
class ScanContext:
    scan_id: int
    scan: dict
    config: dict
    engines: list[str]
    source: dict
    workdir: Path
    deadline: Deadline
    engine_timeout: float
    max_skills: int
    log: Callable[..., None]
    # Заполняют этапы.
    source_meta: dict = field(default_factory=dict)  # что именно сканировали: sha256/размер или коммит
    skills: list[dict] = field(default_factory=list)  # [{"name", "path", "dir": Path}]
    engine_runs: dict = field(default_factory=dict)
    rejected: Optional[dict] = None
