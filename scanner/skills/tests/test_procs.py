"""Запуск движка подпроцессом с таймаутом (D-11, D-23, D-33) -- на настоящих
процессах."""
import os
import sys
import time

from app import procs

PY = sys.executable


def test_ok_captures_output():
    result = procs.run_process([PY, "-c", "print('hello')"], timeout=10)
    assert result.status == "ok"
    assert result.returncode == 0
    assert result.stdout.strip() == "hello"
    assert result.error is None


def test_nonzero_exit_is_failed_with_last_stderr_line():
    result = procs.run_process(
        [PY, "-c", "import sys; sys.stderr.write('a\\nboom\\n'); sys.exit(3)"], timeout=10
    )
    assert result.status == "failed"
    assert result.returncode == 3
    assert result.error == "код возврата 3: boom"


def test_custom_ok_returncodes():
    result = procs.run_process([PY, "-c", "import sys; sys.exit(1)"], timeout=10, ok_returncodes=(0, 1))
    assert result.status == "ok"


def test_missing_binary_is_failed_not_exception():
    result = procs.run_process(["/nonexistent/engine-bin"], timeout=10)
    assert result.status == "failed"
    assert result.returncode is None
    assert result.error.startswith("не удалось запустить")


def test_timeout_kills_process():
    started = time.monotonic()
    result = procs.run_process([PY, "-c", "import time; time.sleep(30)"], timeout=0.5)
    assert result.status == "timeout"
    assert result.error.startswith("превышен таймаут")
    assert time.monotonic() - started < 5


def test_timeout_kills_grandchildren(tmp_path):
    pid_file = tmp_path / "child.pid"
    script = f"sleep 30 & echo $! > {pid_file}; wait"
    result = procs.run_process(["sh", "-c", script], timeout=1)
    assert result.status == "timeout"
    child = int(pid_file.read_text())
    time.sleep(0.2)
    try:
        os.kill(child, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    assert not alive, "внук движка пережил таймаут"


def test_output_is_truncated():
    size = procs.OUTPUT_LIMIT * 2
    result = procs.run_process([PY, "-c", f"print('x' * {size})"], timeout=10)
    assert result.status == "ok"
    assert len(result.stdout) == procs.OUTPUT_LIMIT


def test_no_time_left_does_not_start():
    result = procs.run_process([PY, "-c", "print(1)"], timeout=0)
    assert result.status == "timeout"
    assert result.stdout == ""


def test_env_and_cwd_passed(tmp_path):
    result = procs.run_process(
        [PY, "-c", "import os; print(os.getcwd()); print(os.environ['SKILL_X'])"],
        timeout=10,
        cwd=tmp_path,
        env={**os.environ, "SKILL_X": "42"},
    )
    lines = result.stdout.split()
    assert os.path.realpath(lines[0]) == os.path.realpath(tmp_path)
    assert lines[1] == "42"
