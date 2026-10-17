"""Linux worker-side deadlines and cleanup, independent of HTTP wait timeouts.

This is lifecycle management, not a sandbox against hostile daemonization.
Track descendants AND an inherited marker: MCP SDK/CLI children may have their
own sessions and may outlive their direct parent. Never signal the worker group.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

TASK_MARKER = "MCP_EXECUTION_ID"
STOP_GRACE_SECONDS = 3.0
KILL_WAIT_SECONDS = 2.0
MAX_REPORT_BYTES = 8_000_000


def process_table():
    table = {}
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = path.read_text().rsplit(")", 1)[1].split()
            table[int(path.parent.name)] = (int(fields[1]), int(fields[2]), fields[19], fields[0])
        except (OSError, ValueError, IndexError):
            continue  # A process may exit while /proc is being read.
    return table


class TaskProcesses:
    def __init__(self, pid, marker):
        self.pid, self.marker = pid, marker
        self.known = {}
        initial = process_table().get(pid)
        if initial:
            self.known[pid] = (initial[2], initial[1])
        self.refresh()

    def refresh(self):
        table = process_table()
        # Validate start times before trusting an old PID (PID reuse).
        members = {pid for pid, identity in self.known.items()
                   if pid in table and table[pid][2] == identity[0]}
        for pid, fields in table.items():
            if pid not in members:
                try:
                    if f"{TASK_MARKER}={self.marker}".encode() in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
                        members.add(pid)
                except OSError:
                    pass
        changed = True
        while changed:
            previous = len(members)
            members.update(pid for pid, fields in table.items() if fields[0] in members)
            changed = previous != len(members)
        self.known = {pid: (table[pid][2], table[pid][1]) for pid in members}
        return {pid: table[pid] for pid in members if table[pid][3] != "Z"}

    def send(self, sig):
        alive = self.refresh()
        groups = {fields[1] for fields in alive.values()} - {os.getpgrp()}
        for group in groups:
            try:
                os.killpg(group, sig)
            except ProcessLookupError:
                pass

    def stop(self, process):
        if not self.refresh():
            process.wait()
            return
        self.send(signal.SIGTERM)
        deadline = time.monotonic() + STOP_GRACE_SECONDS
        while self.refresh() and time.monotonic() < deadline:
            process.poll()  # Reap the direct child; container init reaps orphans.
            time.sleep(0.05)
        deadline = time.monotonic() + KILL_WAIT_SECONDS
        while self.refresh() and time.monotonic() < deadline:
            self.send(signal.SIGKILL)
            process.poll()
            time.sleep(0.05)
        if self.refresh():
            raise RuntimeError("Не удалось подтвердить остановку процессов MCP-задания")
        process.wait()


def execute_isolated(task, work):
    timeout = task.get("timeout_seconds", 300)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 300:
        raise ValueError("Таймаут движка должен быть от 1 до 300 секунд")
    marker = uuid4().hex
    report = work / "engine-report.json"
    with tempfile.TemporaryFile() as request, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        request.write(json.dumps(task).encode())
        request.seek(0)
        started = time.monotonic()
        process = subprocess.Popen(
            [sys.executable, "-m", "app.task_runner", str(work), str(report)],
            stdin=request, stdout=stdout, stderr=stderr,
            env={**os.environ, TASK_MARKER: marker}, start_new_session=True,
        )
        tree = TaskProcesses(process.pid, marker)
        try:
            while process.poll() is None:
                tree.refresh()
                if time.monotonic() - started >= timeout:
                    raise TimeoutError(f"Превышен общий таймаут движка {timeout:g} с; выполнение остановлено")
                if max(os.fstat(stdout.fileno()).st_size, os.fstat(stderr.fileno()).st_size) > MAX_REPORT_BYTES:
                    raise RuntimeError("Вывод MCP-задания превышает 8 МБ")
                time.sleep(0.05)
        finally:
            # Also clean leaked descendants after normal exit or an exception.
            # A timeout is reported only after this cleanup has completed.
            tree.stop(process)
        if process.returncode != 0:
            raise RuntimeError(f"Процесс MCP-движка завершился с кодом {process.returncode}")
        if not report.exists() or report.stat().st_size > MAX_REPORT_BYTES:
            raise RuntimeError("Отчёт MCP-задания отсутствует или превышает 8 МБ")
        outcome = json.loads(report.read_text())
        if "error" in outcome:
            raise RuntimeError(outcome["error"])
        return outcome["result"]
