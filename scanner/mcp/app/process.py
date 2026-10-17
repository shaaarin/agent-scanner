"""Bounded subprocesses; never execute source code under analysis."""
import os
import signal
import subprocess
import tempfile
import time

MAX_OUTPUT = 8_000_000

def execute(args, *, timeout=240, cwd=None, env=None):
    child_env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "LANG", "SSL_CERT_FILE", "MCP_EXECUTION_ID"}}
    child_env.update({"SEMGREP_SEND_METRICS": "off", "SEMGREP_ENABLE_VERSION_CHECK": "0", "GIT_TERMINAL_PROMPT": "0"})
    child_env.update(env or {})
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        p = subprocess.Popen(args, cwd=cwd, env=child_env, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                p.poll()
                try:
                    os.killpg(p.pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            # Kill surviving descendants even if their direct parent exited.
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.wait()
            raise RuntimeError(f"Превышен таймаут {timeout} с")
        for stream in (stdout, stderr):
            if stream.tell() > MAX_OUTPUT:
                raise RuntimeError("Отчёт сканера превышает 8 МБ")
            stream.seek(0)
        return p.returncode, stdout.read().decode(errors="replace"), stderr.read().decode(errors="replace")
