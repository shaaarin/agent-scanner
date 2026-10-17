"""Real POSIX groups and signals, inside a Linux MCP worker. No mocks."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from app.task_execution import TaskProcesses, TASK_MARKER, STOP_GRACE_SECONDS
from app.process import execute


with tempfile.TemporaryDirectory(prefix="mcp-stop-check-") as tmp:
    root = Path(tmp)
    marker = uuid4().hex
    # One child deliberately ignores TERM and starts its own session, like
    # the MCP SDK. Another task must stay alive during forced cleanup.
    child_code = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)"
    parent_code = (
        "import subprocess,sys,time; from pathlib import Path; "
        f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}],start_new_session=True); "
        f"Path({str(root / 'child')!r}).write_text(str(p.pid)); time.sleep(120)"
    )
    neighbor = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=True)
    process = subprocess.Popen([sys.executable, "-c", parent_code],
        env={**os.environ, TASK_MARKER: marker}, start_new_session=True)
    tree = TaskProcesses(process.pid, marker)
    try:
        deadline = time.monotonic() + 5
        while not (root / "child").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (root / "child").exists()
        child = int((root / "child").read_text())
        time.sleep(0.2)  # Let the child install its TERM handler.
        tree.refresh()
        assert child in tree.known and neighbor.pid not in tree.known
        started = time.monotonic()
        tree.stop(process)
        elapsed = time.monotonic() - started
        assert STOP_GRACE_SECONDS - 0.1 <= elapsed < STOP_GRACE_SECONDS + 3
        assert not tree.refresh() and neighbor.poll() is None
    finally:
        tree.stop(process)
        os.killpg(neighbor.pid, signal.SIGKILL)
        neighbor.wait()

    # A cooperative task receives TERM and exits without waiting for KILL.
    marker = uuid4().hex
    flag = root / "term"
    ready = root / "ready"
    code = ("import signal,time; from pathlib import Path; "
            f"signal.signal(signal.SIGTERM,lambda *_: (Path({str(flag)!r}).write_text('term'),exit(0))); "
            f"Path({str(ready)!r}).touch(); time.sleep(120)")
    process = subprocess.Popen([sys.executable, "-c", code],
        env={**os.environ, TASK_MARKER: marker}, start_new_session=True)
    tree = TaskProcesses(process.pid, marker)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists()
        started = time.monotonic()
        tree.stop(process)
        assert flag.read_text() == "term" and process.returncode == 0
        assert time.monotonic() - started < STOP_GRACE_SECONDS
    finally:
        tree.stop(process)
    # Inner CLI timeouts must use TERM before KILL as well.
    flag.unlink()
    ready.unlink()
    try:
        execute([sys.executable, "-c", code], timeout=0.5)
    except RuntimeError as exc:
        assert "таймаут" in str(exc)
    else:
        raise AssertionError("CLI must time out")
    assert flag.read_text() == "term"
    print("MCP task stop: TERM, KILL after grace, separate-session descendant, "
          "no live leftovers, neighboring task unaffected OK")
