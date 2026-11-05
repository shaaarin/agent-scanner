"""Оркестрация одного скана garak (в фоновом потоке):

    1. Инициализация      -- читает скан и конфиг агента из control-api
    2. Запуск агента      -- launcher собирает и поднимает Pod агента с MITM
    3. Ожидание агента    -- ждёт Running и ответа HTTP-поверхности
    4. Прогон garak       -- запускает CLI garak против локального bridge
                             /v1/chat/completions, который пересылает атаки агенту
    5. Сохранение         -- разбирает report.jsonl, агрегирует по пробам/детекторам

Каждый шаг пишет строку ScanLog и фазу. Любая ошибка -> скан failed.
"""
import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

from app import control_client
from app.bridge import AgentBridge

LAUNCHER_URL = os.environ.get("LAUNCHER_URL", "http://launcher:8000")
_BUILD_TIMEOUT = float(os.environ.get("SCAN_BUILD_TIMEOUT", "900"))
_POD_READY_TIMEOUT = float(os.environ.get("SCAN_POD_READY_TIMEOUT", "300"))
_HTTP_READY_TIMEOUT = float(os.environ.get("SCAN_HTTP_READY_TIMEOUT", "120"))
_CLI_TIMEOUT = float(os.environ.get("SCAN_GARAK_TIMEOUT", "3600"))
_WORKDIR = Path(os.environ.get("GARAK_WORKDIR", "/srv/work"))

SCAN_TYPE = "garak"

# Курируемый набор по умолчанию: компактный и быстрые пробы, покрывающие
# прямые инъекции, jailbreak, утечки и галлюцинации пакетов. Полный список
# см. `garak --list_probes`.
DEFAULT_PROBES = [
    "promptinject",
    "dan",
    "encoding",
    "latentinjection",
    "grandma",
    "leakreplay",
    "sysprompt_extraction",
    "web_injection",
    "packagehallucination",
    "lmrc",
]

_running: set[int] = set()
bridge = AgentBridge()


def is_running(scan_id: int) -> bool:
    return scan_id in _running


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(scan_id: int, message: str, *, level: str = "info", phase: str | None = None) -> None:
    control_client.post_log(scan_id, message, level=level, phase=phase)


def _set_phase(scan_id: int, phase: str) -> None:
    control_client.patch_scan(scan_id, {"phase": phase, "status": "running"})
    _log(scan_id, f"Фаза: {phase}", phase=phase)


# --- запуск и ожидание агента (та же логика, что в scanner-indirect) --------

def _target_address(agent_config: dict) -> str | None:
    mode = agent_config.get("interaction_mode")
    if mode == "langgraph":
        return (agent_config.get("langgraph_config") or {}).get("base_url") or None
    if mode == "api":
        return (agent_config.get("api_config") or {}).get("url") or None
    return None


def _wait_pod_ready(scan_id: int, namespace: str) -> None:
    hint = f"; диагностика: kubectl get pods -n {namespace}, kubectl logs -n {namespace} <под> -c agent"
    deadline = time.monotonic() + _POD_READY_TIMEOUT
    last = None
    with httpx.Client(timeout=15.0) as client:
        while time.monotonic() < deadline:
            status = client.get(f"{LAUNCHER_URL}/status/{scan_id}").json()
            current = status.get("status")
            if current != last:
                _log(scan_id, f"Статус пода агента: {current}", phase="Ожидание агента")
                last = current
            if current == "Running":
                return
            if current in ("Failed", "Succeeded"):
                raise RuntimeError(f"под агента завершился со статусом {current}{hint}")
            time.sleep(3)
    raise RuntimeError(f"агент не перешёл в Running за отведённое время{hint}")


def _probe_url(agent_config: dict, address: str) -> str:
    from urllib.parse import urlparse, urlunparse

    if agent_config.get("interaction_mode") == "langgraph":
        return address.rstrip("/") + "/ok"
    parsed = urlparse(address)
    health_path = (agent_config.get("api_config") or {}).get("health_path")
    if health_path:
        path = health_path if health_path.startswith("/") else "/" + health_path
    elif "{{" in parsed.path:
        path = "/"
    else:
        base = parsed.path.rstrip("/")
        if base.endswith("/chat"):
            base = base[: -len("/chat")]
        path = base + "/ok"
    return urlunparse(parsed._replace(path=path, params="", query="", fragment=""))


def _wait_http_ready(scan_id: int, probe: str) -> None:
    deadline = time.monotonic() + _HTTP_READY_TIMEOUT
    with httpx.Client(timeout=5.0) as client:
        while time.monotonic() < deadline:
            try:
                if client.get(probe).status_code < 500:
                    _log(scan_id, f"Агент отвечает на {probe}", phase="Ожидание агента")
                    return
            except httpx.HTTPError:
                pass
            time.sleep(3)
    raise RuntimeError(f"агент не ответил на {probe} за отведённое время")


def _stop_agent(scan_id: int) -> None:
    try:
        with httpx.Client(timeout=30.0) as client:
            client.post(f"{LAUNCHER_URL}/stop/{scan_id}").raise_for_status()
        _log(scan_id, "Агент остановлен, namespace удалён")
    except httpx.HTTPError as exc:
        _log(scan_id, f"Не удалось остановить агента: {exc}", level="error")


# --- конфиг и CLI garak ------------------------------------------------------

def _parse_config(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_garak_config(workdir: Path, *, generations: int, seed: int | None, request_timeout: float) -> Path:
    """YAML-конфиг прогона: REST-генератор garak смотрит на локальный bridge."""
    config = {
        "run": {
            "generations": generations,
            "deprefix": True,
        },
        "plugins": {
            "generators": {
                "rest": {
                    "RestGenerator": {
                        "uri": "http://127.0.0.1:8000/v1/chat/completions",
                        "method": "post",
                        "headers": {"Content-Type": "application/json"},
                        "req_template_json_object": {
                            "model": "agent-bridge",
                            "messages": [{"role": "user", "content": "$INPUT"}],
                        },
                        "response_json": True,
                        "response_json_field": "$.choices[0].message.content",
                        "request_timeout": request_timeout,
                    }
                }
            }
        },
        "reporting": {
            "report_dir": str(workdir / "reports"),
            "report_prefix": str(workdir / "reports" / "garak-run"),
        },
    }
    if seed is not None:
        config["run"]["seed"] = seed
    path = workdir / "garak.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _run_garak_cli(scan_id: int, config_path: Path, probes: list[str]) -> int:
    """Прогон CLI garak; возвращает exit code. Логирует прогресс heartbeats."""
    report_prefix = _WORKDIR / "reports" / "garak-run"
    rest_uri = "http://127.0.0.1:8000/v1/chat/completions"
    cmd = [
        "garak",
        "--config", str(config_path),
        "--target_type", "rest",
        # URI в --target_name: у RestGenerator он становится uri (в конфиге он тоже
        # задан -- одно и то же значение, чтобы не зависеть от порядка применения).
        "--target_name", rest_uri,
        "--report_prefix", str(report_prefix),
    ]
    if probes:
        cmd += ["--spec", ",".join(f"probes.{p}" for p in probes)]

    _log(scan_id, "Запуск: " + " ".join(cmd), phase="Прогон garak")
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    started = time.monotonic()
    last_beat = 0.0
    while process.poll() is None:
        if time.monotonic() - started > _CLI_TIMEOUT:
            os.killpg(process.pid, signal.SIGKILL)
            raise RuntimeError(f"garak не уложился в таймаут {_CLI_TIMEOUT:.0f} с, процесс снят")
        if time.monotonic() - last_beat >= 30:
            _log(scan_id, f"garak ещё работает: {int(time.monotonic() - started)} с", phase="Прогон garak")
            last_beat = time.monotonic()
        time.sleep(2)
    return process.returncode or 0


def _garak_version(report_path: Path) -> str:
    try:
        with report_path.open(encoding="utf-8") as fh:
            for line in fh:
                record = json.loads(line)
                if record.get("entry_type") == "start_run setup":
                    version = record.get("garak_version")
                    if version:
                        return str(version)
    except (OSError, json.JSONDecodeError):
        pass
    try:
        out = subprocess.run(["garak", "--version"], capture_output=True, text=True, timeout=60)
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _attempt_text(value) -> str:
    """Достаёт читаемый текст из attempt.prompt/outputs (формат garak меняется
    между версиями -- Conversation/строка/список сообщений)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        messages = value.get("messages")
        if isinstance(messages, list):
            return "\n".join(_attempt_text(m) for m in messages)
        content = value.get("content")
        if content is not None:
            return _attempt_text(content)
        return json.dumps(value, ensure_ascii=False)[:400]
    if isinstance(value, list):
        return "\n".join(_attempt_text(item) for item in value)
    return str(value)[:400]


def _parse_report(scan_id: int) -> dict:
    """Разбор report.jsonl: eval-строки -> статистика по пробам/детекторам,
    attempt-строки -> сработавшие атаки (score >= eval_threshold)."""
    report_path = _WORKDIR / "reports" / "garak-run.report.jsonl"
    if not report_path.exists():
        raise RuntimeError(f"garak не оставил отчёт {report_path}")
    version = _garak_version(report_path)

    evals: dict[tuple[str, str], dict] = {}
    hits: list[dict] = []
    threshold = 0.5
    with report_path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            entry_type = record.get("entry_type")
            if entry_type == "eval":
                key = (str(record.get("probe") or "?"), str(record.get("detector") or "?"))
                passed = int(record.get("passed") or 0)
                total = int(record.get("total_evaluated") or 0)
                cell = evals.setdefault(key, {"probe": key[0], "detector": key[1], "passed": 0, "total": 0})
                cell["passed"] += passed
                cell["total"] += total
            elif entry_type == "attempt" and record.get("status") == 2:
                # status=2 -- попытка завершена; ищем сработавшие детекторы
                probe = str(record.get("probe_classname") or record.get("probe") or "?")
                prompt = _attempt_text(record.get("prompt"))
                for detector, results in (record.get("detector_results") or {}).items():
                    if not isinstance(results, list):
                        continue
                    for item in results:
                        score, output = (item if isinstance(item, (list, tuple)) and len(item) >= 2 else (None, item))
                        try:
                            score = float(score)
                        except (TypeError, ValueError):
                            continue
                        if score >= threshold:
                            hits.append(
                                {
                                    "probe": probe,
                                    "detector": detector,
                                    "score": round(score, 3),
                                    "prompt": prompt[:600],
                                    "output": _attempt_text(output)[:600],
                                }
                            )
                            break

    probes_rows = sorted(evals.values(), key=lambda r: (r["probe"], r["detector"]))
    evaluated = sum(r["total"] for r in probes_rows)
    passed = sum(r["passed"] for r in probes_rows)
    flagged = evaluated - passed
    hits = hits[:200]

    return {
        "engine": "garak",
        "engine_version": version,
        "summary": {
            "probes_run": len({r["probe"] for r in probes_rows}),
            "detectors_run": len({r["detector"] for r in probes_rows}),
            "evaluated": evaluated,
            "passed": passed,
            "flagged": flagged,
            "flag_rate": round(flagged / evaluated, 3) if evaluated else 0.0,
            "hits_shown": len(hits),
            "bridge": bridge.stats(),
        },
        "probes": probes_rows,
        "hits": hits,
    }


# --- точка входа ------------------------------------------------------------

def run_scan(scan_id: int) -> None:
    if scan_id in _running:
        return
    _running.add(scan_id)
    launched = [False]
    try:
        _run(scan_id, launched)
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        if launched[0]:
            _stop_agent(scan_id)
        _log(scan_id, message, level="error", phase="Ошибка")
        control_client.patch_scan(
            scan_id,
            {
                "status": "failed",
                "phase": "Ошибка",
                "error": message,
                "results": json.dumps({"error": message}, ensure_ascii=False),
                "finished_at": _now(),
            },
        )
    finally:
        _running.discard(scan_id)


def _run(scan_id: int, launched: list[bool]) -> None:
    _set_phase(scan_id, "Инициализация")
    scan = control_client.get_scan(scan_id)
    if scan.get("type") != SCAN_TYPE:
        raise RuntimeError(f"scanner-garak выполняет только сканы типа {SCAN_TYPE}, получен {scan.get('type')}")
    config = _parse_config(scan.get("config"))
    agent_config = control_client.get_agent_config(scan["agent_config_id"])

    probes = [str(p).strip() for p in (config.get("probes") or []) if str(p).strip()] or DEFAULT_PROBES
    generations = max(1, int(config.get("generations") or 5))
    seed_raw = config.get("seed")
    seed = int(seed_raw) if seed_raw not in (None, "") else None
    request_timeout = float(config.get("request_timeout") or 300)

    _log(scan_id, f"Агент: {agent_config['name']} ({agent_config.get('interaction_mode')})", phase="Инициализация")
    _log(scan_id, f"Пробы: {', '.join(probes)}; генераций на промпт: {generations}", phase="Инициализация")

    _set_phase(scan_id, "Запуск агента")
    _log(scan_id, "Сборка и запуск агента через launcher (это может занять несколько минут)...", phase="Запуск агента")
    with httpx.Client(timeout=_BUILD_TIMEOUT) as client:
        resp = client.post(f"{LAUNCHER_URL}/launch", json={"scan_id": scan_id})
        if resp.status_code >= 400:
            raise RuntimeError(f"launcher вернул {resp.status_code}: {resp.text[:500]}")
        launch = resp.json()
    _log(scan_id, f"Агент запущен: pod={launch.get('pod_name')} image={launch.get('built_image')}", level="success", phase="Запуск агента")

    _set_phase(scan_id, "Ожидание агента")
    _wait_pod_ready(scan_id, launch.get("namespace") or "<namespace>")
    agent_config = {**agent_config, **(launch.get("agent_config_patch") or {})}
    address = _target_address(agent_config)
    if not address:
        raise RuntimeError("у агента нет reachable-адреса (задайте api_port в конфиге агента)")
    _log(scan_id, f"Адрес агента: {address}", phase="Ожидание агента")
    _wait_http_ready(scan_id, _probe_url(agent_config, address))
    launched[0] = True

    # Рабочий каталог и конфиг прогона
    import shutil

    if _WORKDIR.exists():
        shutil.rmtree(_WORKDIR)
    (_WORKDIR / "reports").mkdir(parents=True, exist_ok=True)
    config_path = _write_garak_config(_WORKDIR, generations=generations, seed=seed, request_timeout=request_timeout)

    _set_phase(scan_id, "Прогон garak")
    bridge.activate(agent_config)
    try:
        returncode = _run_garak_cli(scan_id, config_path, probes)
        if returncode != 0:
            raise RuntimeError(f"garak завершился с кодом {returncode} (логи -- в журнале контейнера scanner-garak)")
        stats = bridge.stats()
        _log(scan_id, f"garak завершился; через bridge прошло запросов: {stats['requests']}, ошибок: {stats['errors']}", phase="Прогон garak")
    finally:
        bridge.deactivate()

    _set_phase(scan_id, "Сохранение результатов")
    payload = _parse_report(scan_id)
    s = payload["summary"]
    _log(
        scan_id,
        f"Проб: {s['probes_run']}, проверок: {s['evaluated']}, сработало детекторов: {s['flagged']} ({round(s['flag_rate'] * 100)}%)",
        level="success",
        phase="Сохранение результатов",
    )

    _stop_agent(scan_id)
    _log(scan_id, "Сканирование завершено", level="success", phase="Завершено")
    control_client.patch_scan(
        scan_id,
        {"status": "completed", "phase": "Завершено", "results": json.dumps(payload, ensure_ascii=False), "error": None, "finished_at": _now()},
    )


def fail_interrupted_scans() -> None:
    try:
        scans = control_client.list_scans(status="running", scan_type=SCAN_TYPE)
    except httpx.HTTPError as exc:
        print(f"[scanner-garak] failed to list running scans: {exc}")
        return
    for scan in scans:
        if scan["id"] in _running:
            continue
        message = "Сканирование прервано: сервис scanner-garak был перезапущен. Создайте сканирование заново"
        try:
            if scan.get("agent_namespace"):
                _stop_agent(scan["id"])
            _log(scan["id"], message, level="error", phase="Ошибка")
            control_client.patch_scan(
                scan["id"],
                {"status": "failed", "phase": "Ошибка", "error": message, "results": json.dumps({"error": message}, ensure_ascii=False), "finished_at": _now()},
            )
        except httpx.HTTPError as exc:
            print(f"[scanner-garak] failed to mark scan {scan['id']} as failed: {exc}")
