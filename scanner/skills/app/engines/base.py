"""Общая часть адаптеров движков (D-11, D-23, D-37).

Адаптер запускает CLI движка в отдельном процессе (`app.procs`), читает его
JSON и приводит находки к единой форме §2.7. Движок «не отработал» -- это
`status` failed/timeout в `EngineRun`, а не исключение: решение «частичный
результат или failed» принимает этап анализа (D-23).

Место под LLM (D-37): `run(..., llm=None)`. В MVP LLM нет, адаптер с `llm`
не запускается.
"""
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app import procs

SEVERITIES = ("critical", "high", "medium", "low", "info")
# Свои правила (D-18): rules/yara -- исходники, rules/cisco-pack -- пак для
# Cisco, собирается rules/build_pack.py при сборке образа (D-35).
DEFAULT_RULES_DIR = Path(__file__).resolve().parents[2] / "rules"


def rules_dir() -> Path:
    return Path(os.environ.get("SKILLS_RULES_DIR") or DEFAULT_RULES_DIR)
MAX_REPORT_BYTES = 20 * 1024 * 1024  # JSON движка больше -- считаем сбоем
MAX_FINDINGS = 500  # на один запуск движка по одному скиллу
MAX_TEXT = 2000  # символов в title/finding/fix
MAX_SNIPPET = 500


@dataclass
class Finding:
    engine: str
    rule_id: str
    severity: str  # critical | high | medium | low | info
    confidence: Optional[float]
    category: Optional[str]
    file: Optional[str]  # относительно папки скилла
    line: Optional[int]
    title: str
    finding: Optional[str]
    fix: Optional[str]
    snippet: Optional[str] = None

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class EngineRun:
    engine: str
    status: str  # ok | failed | timeout
    version: str
    duration_sec: float = 0.0
    error: Optional[str] = None
    own_verdict: Optional[str] = None  # справочно (D-10)
    llm: bool = False
    findings: list[Finding] = field(default_factory=list)
    # Что важно знать о прогоне, но не находка: OSV.dev недоступен (D-50),
    # движок проверил не все файлы, находки обрезаны.
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class EngineOutputError(ValueError):
    """JSON движка не разобрать -- движок «не отработал»."""


def normalize_severity(value) -> str:
    """Severity движка -> одно из SEVERITIES. Cisco `SAFE` -- info.
    Незнакомое значение не прячем в info: medium виден в отчёте и не меняет
    вердикт сам по себе (D-12)."""
    text = str(value or "").strip().lower()
    if text in SEVERITIES:
        return text
    if text in ("safe", "none", "informational"):
        return "info"
    return "medium"


def clip(value, limit: int = MAX_TEXT) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1] + "…"


def to_int(value) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def to_confidence(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 3) if 0 <= number <= 1 else None


def relative_file(value, skill_dir: Path) -> Optional[str]:
    """Путь файла находки относительно папки скилла. Абсолютный путь вне
    скилла (временная папка сканера) в отчёт не попадает -- только имя."""
    if not value:
        return None
    text = str(value).replace("\\", "/")
    path = Path(text)
    if not path.is_absolute():
        return text.removeprefix("./") or None
    for root in (skill_dir, skill_dir.resolve()):
        try:
            return path.relative_to(root).as_posix() or None
        except ValueError:
            continue
    return path.name or None


def sort_key(finding: Finding):
    return (SEVERITIES.index(finding.severity), finding.file or "", finding.line or 0, finding.rule_id)


def engine_env(home: Path) -> dict[str, str]:
    """Окружение процесса движка: только необходимое. Секретов у сервиса нет,
    но и ничего лишнего движку не передаём; HOME/TMPDIR -- свои на каждый
    запуск, чтобы кэши движков не переживали скан."""
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(home),
        "TMPDIR": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "NO_COLOR": "1",
    }


class Engine:
    name: str = ""
    label: str = ""
    version: str = ""
    binary_env: str = ""
    default_binary: str = ""
    # Коды возврата, при которых отчёт движка валиден (наличие отчёта
    # проверяется отдельно).
    ok_returncodes: tuple[int, ...] = (0,)

    @property
    def binary(self) -> str:
        return os.environ.get(self.binary_env) or self.default_binary

    # Переопределяют адаптеры.
    def command(self, skill_dir: Path, output: Path) -> list[str]:
        raise NotImplementedError

    def extra_env(self) -> dict[str, str]:
        return {}

    def missing_rules(self) -> Optional[str]:
        """Текст предупреждения, если свои правила не подключены."""
        return None

    def parse(self, data: dict, skill_dir: Path, run: EngineRun) -> None:
        """Заполняет run.findings / own_verdict / warnings из JSON движка."""
        raise NotImplementedError

    def inspect_stderr(self, stderr: str, run: EngineRun) -> None:
        """Предупреждения, которые движок пишет только в stderr."""

    def run(self, skill_dir: Path, *, workdir: Path, timeout: float, llm=None) -> EngineRun:
        if llm is not None:
            raise NotImplementedError("LLM-анализ отключён в этой версии scanner-skills (D-37)")
        workdir.mkdir(parents=True, exist_ok=True)
        output = workdir / "report.json"
        home = workdir / "home"
        home.mkdir(exist_ok=True)
        started = time.monotonic()
        result = procs.run_process(
            self.command(skill_dir, output),
            timeout=timeout,
            cwd=workdir,
            env={**engine_env(home), **self.extra_env()},
            ok_returncodes=self.ok_returncodes,
        )
        run = EngineRun(self.name, result.status, self.version, duration_sec=round(result.duration_sec, 2))
        if missing := self.missing_rules():
            run.warnings.append(missing)
        if result.status != "ok":
            run.error = result.error
            return run
        try:
            data = self._read_report(output)
            self.parse(data, skill_dir, run)
        except EngineOutputError as exc:
            run.status = "failed"
            run.error = str(exc)
            run.findings = []
            return run
        self.inspect_stderr(result.stderr, run)
        if len(run.findings) > MAX_FINDINGS:
            run.warnings.append(f"показаны первые {MAX_FINDINGS} находок из {len(run.findings)}")
        run.findings = sorted(run.findings, key=sort_key)[:MAX_FINDINGS]
        run.duration_sec = round(time.monotonic() - started, 2)
        return run

    def _read_report(self, output: Path) -> dict:
        if not output.is_file() or output.stat().st_size == 0:
            raise EngineOutputError("движок завершился без отчёта")
        if output.stat().st_size > MAX_REPORT_BYTES:
            raise EngineOutputError(f"отчёт движка больше {MAX_REPORT_BYTES // (1024 * 1024)} МиБ")
        try:
            data = json.loads(output.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise EngineOutputError(f"отчёт движка не является JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise EngineOutputError("отчёт движка не является JSON-объектом")
        return data


def as_list(value) -> list:
    return value if isinstance(value, list) else []


def as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}
