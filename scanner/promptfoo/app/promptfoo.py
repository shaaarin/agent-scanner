"""Запуск `promptfoo code-scans run` и перевод его JSON-ответа в формат
`Scan.results` для страницы скана.

Что важно про CLI (promptfoo 0.123.x):
- анализ выполняет облако Promptfoo, ключ -- `PROMPTFOO_API_KEY` из окружения;
- с `--json` stdout содержит только итоговый JSON, ошибки идут в stderr,
  до конца работы CLI ничего не печатает -- поэтому в журнал пишем heartbeat;
- код возврата 0 -- скан прошёл (находки на него не влияют), иначе ошибка;
- ответ: {success, review?, comments[], error?, skipReason?}, в каждом
  comment: file, line, startLine?, severity, finding, fix?, aiAgentPrompt?.
"""
import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

PROMPTFOO_BIN = os.environ.get("PROMPTFOO_BIN", "promptfoo")
SCAN_TIMEOUT = float(os.environ.get("SCAN_CODE_TIMEOUT", "1800"))
HEARTBEAT_SECONDS = 30

SEVERITIES = ["critical", "high", "medium", "low"]

LogFn = Callable[[str, str], None]  # (level, message)


class PromptfooError(RuntimeError):
    pass


def version() -> str:
    try:
        result = subprocess.run([PROMPTFOO_BIN, "--version"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PromptfooError(f"promptfoo не запускается: {exc}") from exc
    if result.returncode != 0:
        raise PromptfooError(f"promptfoo --version завершился с кодом {result.returncode}: {result.stderr.strip()[:300]}")
    return result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "unknown"


def run_code_scan(
    repo_path: Path,
    base: str,
    compare: str,
    *,
    min_severity: str,
    guidance: str | None,
    on_log: LogFn,
) -> dict:
    """Запускает CLI и возвращает его JSON-ответ. Бросает PromptfooError при
    ошибке, таймауте или неразборчивом ответе."""
    args = [
        PROMPTFOO_BIN,
        "code-scans",
        "run",
        str(repo_path),
        "--base",
        base,
        "--compare",
        compare,
        "--min-severity",
        min_severity,
        "--json",
    ]
    api_host = os.environ.get("PROMPTFOO_CODE_SCAN_API_HOST", "").strip()
    if api_host:
        args += ["--api-host", api_host]
    if guidance:
        args += ["--guidance", guidance]

    # cwd -- вне сканируемого репо: promptfoo не запускает filesystem-MCP
    # из каталога внутри него.
    proc = subprocess.Popen(
        args,
        cwd=str(repo_path.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        # своя группа процессов: при таймауте останавливаем и дочерний
        # filesystem-MCP, иначе он остаётся висеть в контейнере
        start_new_session=True,
    )

    stdout_chunks: list[str] = []
    stderr_lines: list[str] = []

    def _read_stdout() -> None:
        assert proc.stdout is not None
        stdout_chunks.append(proc.stdout.read())

    def _read_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            line = line.rstrip()
            if line:
                stderr_lines.append(line)
                on_log("info", f"promptfoo: {line}")

    readers = [threading.Thread(target=_read_stdout, daemon=True), threading.Thread(target=_read_stderr, daemon=True)]
    for reader in readers:
        reader.start()

    started = time.monotonic()
    while True:
        try:
            proc.wait(timeout=HEARTBEAT_SECONDS)
            break
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - started
            if elapsed >= SCAN_TIMEOUT:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                raise PromptfooError(f"анализ не уложился в {int(SCAN_TIMEOUT // 60)} мин и был остановлен")
            on_log("info", f"Анализ идёт, прошло {int(elapsed // 60)} мин {int(elapsed % 60)} с")

    for reader in readers:
        reader.join(timeout=10)

    stdout = "".join(stdout_chunks).strip()
    tail = "\n".join(stderr_lines[-10:])

    if proc.returncode != 0:
        detail = tail or stdout[:500] or "без вывода"
        raise PromptfooError(f"promptfoo завершился с кодом {proc.returncode}: {detail}")

    try:
        response = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise PromptfooError(f"некорректный ответ promptfoo (не JSON): {stdout[:300] or 'пусто'}") from exc

    if not isinstance(response, dict):
        raise PromptfooError("некорректный ответ promptfoo: ожидался JSON-объект")
    if response.get("success") is False:
        raise PromptfooError(f"promptfoo сообщил об ошибке: {response.get('error') or 'без описания'}")
    return response


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_results(response: dict, *, meta: dict) -> dict:
    """Ответ promptfoo -> `Scan.results`. Неизвестные поля игнорируются,
    отсутствующие становятся null: формат CLI 0.x может меняться."""
    findings = []
    notes = []
    for comment in response.get("comments") or []:
        if not isinstance(comment, dict):
            continue
        severity = str(comment.get("severity") or "").lower()
        if severity in SEVERITIES:
            findings.append(
                {
                    "file": comment.get("file"),
                    "line": _as_int(comment.get("line")),
                    "start_line": _as_int(comment.get("startLine")),
                    "severity": severity,
                    "finding": comment.get("finding") or "",
                    "fix": comment.get("fix"),
                    "ai_agent_prompt": comment.get("aiAgentPrompt"),
                }
            )
        elif comment.get("finding"):
            # severity "none" -- общий комментарий сканера, а не находка.
            notes.append(str(comment["finding"]))

    findings.sort(key=lambda f: (SEVERITIES.index(f["severity"]), f["file"] or "", f["line"] or 0))

    review_parts = [response.get("review"), *notes, response.get("skipReason")]
    review = "\n\n".join(str(part).strip() for part in review_parts if part and str(part).strip())

    summary = {severity: 0 for severity in SEVERITIES}
    for finding in findings:
        summary[finding["severity"]] += 1
    summary["total"] = len(findings)

    return {
        "engine": "promptfoo-code-scans",
        **meta,
        "review": review or None,
        "summary": summary,
        "findings": findings,
    }
