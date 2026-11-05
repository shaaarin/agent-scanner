"""Генерация и прогон red-team тестов через CLI promptfoo (`redteam run`).

Цель атак (top-level targets) -- локальный OpenAI-совместимый bridge
(app/bridge.py), который пересылает промпты тестируемому агенту. Модель
генерации атак и оценки ответов (redteam.provider, он же грейдер) --
LLM_PROVIDER_* из .env, по конвенции «никаких моков».
"""
import json
import os
import signal
import subprocess
import time
from pathlib import Path

import yaml

PROMPTFOO_BIN = os.environ.get("PROMPTFOO_BIN", "promptfoo")
WORKDIR = Path(os.environ.get("RETEAM_WORKDIR", "/srv/work"))

# Курируемый набор плагинов по умолчанию; переопределяется в конфиге скана.
# Полный список -- https://www.promptfoo.dev/docs/red-team/plugins
DEFAULT_PLUGINS = [
    "prompt-extraction",
    "prompt-injection",
    "hijacking",
    "excessive-agency",
    "pii:direct",
    "ssrf",
]
DEFAULT_LANGUAGE = "Russian"


class PromptfooError(RuntimeError):
    pass


def version() -> str:
    try:
        out = subprocess.run([PROMPTFOO_BIN, "version"], capture_output=True, text=True, timeout=120)
        return (out.stdout or out.stderr).strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _provider_config(base_url: str, api_key: str, model: str) -> dict:
    return {
        "id": f"openai:chat:{model}",
        "config": {
            "apiBaseUrl": base_url,
            "apiKey": api_key,
        },
    }


def write_config(
    workdir: Path,
    *,
    provider_base_url: str,
    provider_api_key: str,
    provider_model: str,
    purpose: str,
    plugins: list[str],
    num_tests: int,
    language: str | None,
    max_concurrency: int,
) -> Path:
    """promptfooconfig.yaml: цель -- наш bridge, генератор/грейдер -- LLM_PROVIDER."""
    config = {
        "description": f"agent-redteam-{workdir.name}",
        "targets": [
            _provider_config("http://127.0.0.1:8000/v1", "dummy", "agent-bridge"),
        ],
        "prompts": ["{{prompt}}"],
        "redteam": {
            "purpose": purpose,
            "numTests": num_tests,
            "plugins": plugins,
            "provider": _provider_config(provider_base_url, provider_api_key, provider_model),
            "maxConcurrency": max_concurrency,
        },
    }
    if language:
        config["redteam"]["language"] = language
    path = workdir / "promptfooconfig.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def run_redteam(scan_id: int, *, on_log, heartbeat: int = 60) -> Path:
    """`promptfoo redteam run` в рабочем каталоге; возвращает путь к out.json.

    on_log(message, level=..., phase=...) пишет строки в ScanLog; каждые
    `heartbeat` секунд -- строка «ещё работает»."""
    WORKDIR.mkdir(parents=True, exist_ok=True)
    out_path = WORKDIR / "output.json"
    cmd = [
        PROMPTFOO_BIN,
        "redteam",
        "run",
        "--config", "promptfooconfig.yaml",
        "--output", str(out_path),
    ]
    on_log("Запуск: " + " ".join(cmd))
    env = {
        **os.environ,
        "PROMPTFOO_DISABLE_TELEMETRY": "1",
        "PROMPTFOO_DISABLE_UPDATE": "1",
    }
    timeout = float(os.environ.get("SCAN_RETEAM_TIMEOUT", "3600"))
    process = subprocess.Popen(
        cmd,
        cwd=str(WORKDIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
        env=env,
    )
    started = time.monotonic()
    last_beat = 0.0
    while process.poll() is None:
        if time.monotonic() - started > timeout:
            os.killpg(process.pid, signal.SIGKILL)
            raise PromptfooError(f"promptfoo не уложился в таймаут {timeout:.0f} с, процесс снят")
        if time.monotonic() - last_beat >= heartbeat:
            on_log(f"promptfoo ещё работает: {int(time.monotonic() - started)} с")
            last_beat = time.monotonic()
        time.sleep(2)
    if process.returncode != 0:
        tail = (process.stdout.read() or "")[-2000:] if process.stdout else ""
        raise PromptfooError(f"promptfoo redteam run завершился с кодом {process.returncode}: {tail}")
    if not out_path.exists():
        raise PromptfooError(f"promptfoo не записал {out_path}")
    return out_path


def _output_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("output") or value.get("content") or json.dumps(value, ensure_ascii=False))
    if isinstance(value, list):
        return "\n".join(_output_text(item) for item in value)
    return str(value)


def _test_prompt(test_case: dict) -> str:
    variables = test_case.get("vars") or {}
    prompt = variables.get("prompt")
    if isinstance(prompt, str):
        return prompt
    for value in variables.values():
        if isinstance(value, str):
            return value
    return ""


def build_results(out_path: Path, *, meta: dict) -> dict:
    """Разбор output.json: тест = одна атака; `success: false` -- агент
    выполнил вредоносный запрос (уязвимость), `success: true` -- устоял."""
    data = json.loads(out_path.read_text(encoding="utf-8"))
    block = data.get("results")
    rows = block.get("results") if isinstance(block, dict) else block
    if not isinstance(rows, list):
        raise PromptfooError("неожиданный формат output.json: нет списка results")

    findings: list[dict] = []
    per_plugin: dict[str, dict] = {}
    total = passed = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        test_case = row.get("testCase") or row.get("test_case") or {}
        metadata = test_case.get("metadata") or {}
        plugin = str(metadata.get("redteamPlugin") or metadata.get("pluginId") or metadata.get("plugin") or "?")
        cell = per_plugin.setdefault(plugin, {"plugin": plugin, "tests": 0, "failed": 0})
        cell["tests"] += 1
        total += 1
        success = bool(row.get("success"))
        if success:
            passed += 1
            continue
        cell["failed"] += 1
        findings.append(
            {
                "plugin": plugin,
                "severity": metadata.get("severity") or test_case.get("metadata", {}).get("severity"),
                "prompt": _test_prompt(test_case)[:800],
                "output": _output_text((row.get("response") or {}).get("output"))[:800],
                "error": (row.get("error") or "")[:400],
            }
        )
    findings = findings[:200]
    failed = total - passed

    plugins_rows = sorted(per_plugin.values(), key=lambda r: (-r["failed"], r["plugin"]))
    return {
        "engine": "promptfoo-redteam",
        "engine_version": meta.get("engine_version", "unknown"),
        "purpose": meta.get("purpose"),
        "plugins_configured": meta.get("plugins", []),
        "summary": {
            "tests": total,
            "passed": passed,
            "failed": failed,
            "fail_rate": round(failed / total, 3) if total else 0.0,
            "findings_shown": len(findings),
            "duration_sec": meta.get("duration_sec"),
        },
        "plugins": plugins_rows,
        "findings": findings,
    }
