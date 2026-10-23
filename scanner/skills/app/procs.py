"""Запуск внешней программы (CLI движка) в отдельном процессе с таймаутом
(D-11, D-33).

Процесс стартует в своей сессии, поэтому по таймауту убивается вся группа --
вместе с дочерними процессами движка, а не только верхний. Вывод
ограничивается: в журнал скана уходит хвост stderr, а не мегабайты.
"""
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

OUTPUT_LIMIT = 64 * 1024  # байт stdout/stderr, которые сохраняем


@dataclass
class ProcessResult:
    status: str  # ok | failed | timeout
    returncode: Optional[int]
    stdout: str
    stderr: str
    duration_sec: float
    error: Optional[str] = None


def _tail(data: bytes | None) -> str:
    if not data:
        return ""
    return data[-OUTPUT_LIMIT:].decode("utf-8", errors="replace")


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_process(
    cmd: list[str],
    *,
    timeout: float,
    cwd: Optional[Path] = None,
    env: Optional[dict[str, str]] = None,
    ok_returncodes: tuple[int, ...] = (0,),
) -> ProcessResult:
    """Запускает `cmd` и ждёт не дольше `timeout` секунд. Никогда не бросает
    исключение из-за самой программы: незапускаемая команда, ненулевой код
    или таймаут -- это `status` в результате (движок «не отработал», D-23).
    `ok_returncodes` -- коды, которые считаются успехом (у сканеров код 1
    часто означает «есть находки»)."""
    started = time.monotonic()
    if timeout <= 0:
        return ProcessResult("timeout", None, "", "", 0.0, error="не осталось времени на запуск")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        return ProcessResult("failed", None, "", "", time.monotonic() - started, error=f"не удалось запустить: {exc}")

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        stdout, stderr = proc.communicate()
        return ProcessResult(
            "timeout",
            None,
            _tail(stdout),
            _tail(stderr),
            time.monotonic() - started,
            error=f"превышен таймаут {timeout:.0f} с",
        )
    finally:
        # Внуки, пережившие родителя, не должны оставаться в контейнере.
        if proc.returncode is not None:
            _kill_group(proc)

    duration = time.monotonic() - started
    if proc.returncode in ok_returncodes:
        return ProcessResult("ok", proc.returncode, _tail(stdout), _tail(stderr), duration)
    last_line = (_tail(stderr).strip().splitlines() or [""])[-1][:300]
    return ProcessResult(
        "failed",
        proc.returncode,
        _tail(stdout),
        _tail(stderr),
        duration,
        error=f"код возврата {proc.returncode}" + (f": {last_line}" if last_line else ""),
    )
