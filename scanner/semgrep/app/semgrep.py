"""Запуск локального `semgrep scan` и перевод его JSON-отчёта в формат
`Scan.results` страницы скана (общий с code_scan формат находок).

Про CLI (semgrep 1.180.x):
- с `--json` stdout содержит только итоговый JSON-отчёт, прогресс -- в stderr;
- код возврата 0 -- анализ выполнен полностью (находки на него не влияют);
  с `--strict` ошибка любого правила роняет весь прогон -- как в SAST
  scanner-mcp, анализ фейлится закрыто, а не молча пропускает файлы;
- официальный набор (`--config p/...`) скачивается из Semgrep Registry при
  запуске -- без интернета такой скан падает с ошибкой в отчёте.
"""
import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

SEMGREP_BIN = os.environ.get("SEMGREP_BIN", "/opt/semgrep/bin/semgrep")
SCAN_TIMEOUT = float(os.environ.get("SCAN_SEMGREP_TIMEOUT", "1800"))
HEARTBEAT_SECONDS = 30

# Серьёзности для фильтра min_severity; у semgrep уровня critical нет,
# находки Registry-правил с ERROR попадают в high.
SEVERITIES = ["low", "medium", "high", "critical"]
_SEMGREP_SEVERITY_MAP = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}

LogFn = Callable[[str, str], None]  # (level, message)


class SemgrepError(RuntimeError):
    pass


def version() -> str:
    try:
        result = subprocess.run(
            [SEMGREP_BIN, "--version", "--disable-version-check"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SemgrepError(f"semgrep не запускается: {exc}") from exc
    if result.returncode != 0:
        raise SemgrepError(f"semgrep --version завершился с кодом {result.returncode}: {result.stderr.strip()[:300]}")
    return result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "unknown"


def run_scan(repo_path: Path, rule_configs: list[str], *, on_log: LogFn) -> dict:
    """Запускает semgrep по репозиторию и возвращает его JSON-отчёт.
    Бросает SemgrepError при ошибке, таймауте или неполном анализе."""
    args = [SEMGREP_BIN, "scan"]
    for config in rule_configs:
        args += ["--config", config]
    args += [
        "--json",
        "--metrics=off",
        "--disable-version-check",
        # .gitignore уважается по умолчанию: сгенерированные каталоги и
        # зависимости репозитория в анализ не попадают.
        "--timeout",
        "10",
        "--max-target-bytes",
        "1000000",
        "--exclude",
        "node_modules",
        "--exclude",
        ".git",
        "--exclude",
        ".venv",
        "--strict",
        ".",
    ]

    proc = subprocess.Popen(
        args,
        cwd=str(repo_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
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
                raise SemgrepError(f"анализ не уложился в {int(SCAN_TIMEOUT // 60)} мин и был остановлен")
            on_log("info", f"Анализ идёт, прошло {int(elapsed // 60)} мин {int(elapsed % 60)} с")

    for reader in readers:
        reader.join(timeout=10)

    stdout = "".join(stdout_chunks).strip()

    if proc.returncode != 0:
        # При --strict настоящий причину называют errors в JSON-отчёте;
        # stdout содержит его даже при ненулевом коде возврата.
        reported = ""
        try:
            report = json.loads(stdout)
            if isinstance(report, dict) and report.get("errors"):
                reported = "semgrep не выполнил полный анализ: " + json.dumps(report["errors"], ensure_ascii=False)[:1000]
        except json.JSONDecodeError:
            pass
        if not reported:
            detail = "\n".join(stderr_lines[-5:]) or stdout[:500] or "без вывода"
            reported = f"semgrep завершился с кодом {proc.returncode}: {detail[:800]}"
        raise SemgrepError(reported)

    try:
        report = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise SemgrepError(f"некорректный ответ semgrep (не JSON): {stdout[:300] or 'пусто'}") from exc
    if not isinstance(report, dict):
        raise SemgrepError("некорректный ответ semgrep: ожидался JSON-объект")
    if report.get("errors"):
        raise SemgrepError(
            "semgrep не выполнил полный анализ: "
            + json.dumps(report["errors"], ensure_ascii=False)[:1200]
        )
    return report


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_list(value) -> list[str]:
    if value is None:
        return []
    return [str(item) for item in value] if isinstance(value, list) else [str(value)]


def _severity(result: dict) -> str:
    extra = result.get("extra") or {}
    return _SEMGREP_SEVERITY_MAP.get(str(extra.get("severity", "")).upper(), "low")


def _fix_text(result: dict) -> str | None:
    """Рекомендация из метаданных правила (CWE и ссылки на документацию);
    сам текст проблемы -- в поле finding, как у прочих правил."""
    metadata = (result.get("extra") or {}).get("metadata") or {}
    parts: list[str] = []
    cwe = _as_list(metadata.get("cwe"))
    if cwe:
        parts.append("Категория: " + ", ".join(cwe))
    references = [str(item) for item in metadata.get("references") or []]
    if references:
        parts.append("Подробнее: " + ", ".join(references))
    return "\n".join(parts) or None


def build_results(report: dict, *, meta: dict, coverage: str, min_severity: str) -> dict:
    """JSON-отчёт semgrep -> `Scan.results`. Формат находок общий с
    code_scan: по нему страницу скана рендерит CodeScanResults. Находки ниже
    `min_severity` в результаты не попадают."""
    threshold = SEVERITIES.index(min_severity)
    findings = []
    for result in report.get("results") or []:
        if not isinstance(result, dict):
            continue
        extra = result.get("extra") or {}
        start = result.get("start") or {}
        end = result.get("end") or {}
        severity = _severity(result)
        if SEVERITIES.index(severity) < threshold:
            continue
        findings.append(
            {
                "file": result.get("path"),
                "line": _as_int(end.get("line")),
                "start_line": _as_int(start.get("line")),
                "severity": severity,
                "finding": extra.get("message") or "",
                "fix": _fix_text(result),
                "ai_agent_prompt": None,
                "rule_id": result.get("check_id"),
            }
        )

    findings.sort(
        key=lambda f: (
            -SEVERITIES.index(f["severity"]),
            f["file"] or "",
            f["start_line"] or 0,
        )
    )

    summary = {severity: 0 for severity in SEVERITIES}
    for finding in findings:
        summary[finding["severity"]] += 1
    summary["total"] = len(findings)

    scanned = (report.get("paths") or {}).get("scanned") or []
    return {
        "engine": "semgrep",
        **meta,
        "review": coverage,
        "files_in_scope": len(scanned),
        "summary": summary,
        "findings": findings,
    }
