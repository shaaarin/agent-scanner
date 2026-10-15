"""Образ scanner-skills (подзадача 4): закреплённые версии движков (D-17),
lock-файлы с хэшами (D-32, D-48), раздельные окружения (D-11).

Статические проверки файлов идут всегда. Проверки готового образа помечены
`docker` и пропускаются, если нет docker или образа (`SKILLS_IMAGE`,
по умолчанию agent-scanner-scanner-skills -- его собирает
`docker compose build scanner-skills`)."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCKS = {name: ROOT / f"requirements-{name}.lock" for name in ("service", "cisco", "skillspector")}
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")

CISCO_VERSION = "2.1.0"
SKILLSPECTOR_VERSION = "2.11.2"
SKILLSPECTOR_COMMIT = "69dcdfb74487d361ba4c811d088cfdea2ff3a9dc"
IMAGE = os.environ.get("SKILLS_IMAGE", "agent-scanner-scanner-skills")


def _requirements(lock: Path) -> list[str]:
    """Блоки «пакет==версия \\ --hash=...» lock-файла."""
    text = lock.read_text(encoding="utf-8")
    return [block for block in re.split(r"\n(?=[A-Za-z0-9])", text) if re.match(r"[A-Za-z0-9]", block)]


def _pinned(lock: Path) -> dict[str, str]:
    result = {}
    for block in _requirements(lock):
        name, _, version = block.split()[0].partition("==")
        result[name.lower()] = version
    return result


# --- lock-файлы ---------------------------------------------------------------------


@pytest.mark.parametrize("name", LOCKS)
def test_every_requirement_pinned_and_hashed(name):
    blocks = _requirements(LOCKS[name])
    assert blocks, f"{LOCKS[name].name} пуст"
    for block in blocks:
        spec = block.split()[0]
        assert re.fullmatch(r"[A-Za-z0-9._\-\[\],]+==[^\s;]+", spec), f"не закреплён: {spec}"
        assert "--hash=sha256:" in block, f"без хэша: {spec}"


@pytest.mark.parametrize("name", LOCKS)
def test_no_vcs_or_url_requirements(name):
    text = LOCKS[name].read_text(encoding="utf-8")
    assert "git+" not in text and " @ " not in text


@pytest.mark.parametrize("name", LOCKS)
def test_lock_uses_pypi_only(name):
    text = LOCKS[name].read_text(encoding="utf-8")
    indexes = re.findall(r"^--(?:extra-)?index-url\s+(\S+)", text, re.M)
    assert indexes == ["https://pypi.org/simple"]


def test_engine_versions_match_d17():
    assert _pinned(LOCKS["cisco"])["cisco-ai-skill-scanner"] == CISCO_VERSION
    assert "cisco-ai-skill-scanner==2.1.0" in (ROOT / "requirements-cisco.in").read_text()
    spector_in = (ROOT / "requirements-skillspector.in").read_text()
    assert f"@{SKILLSPECTOR_COMMIT}" in spector_in


def test_environments_are_separate():
    cisco, spector, service = (_pinned(LOCKS[n]) for n in ("cisco", "skillspector", "service"))
    assert "litellm" in cisco and "litellm" not in spector and "litellm" not in service
    assert "langgraph" in spector and "langgraph" not in cisco and "langgraph" not in service
    assert "cisco-ai-skill-scanner" not in service and "yara-python" not in service
    # Сборка SkillSpector без изоляции берёт backend из lock (D-48).
    assert "hatchling" in spector


def test_service_lock_covers_service_imports():
    service = _pinned(LOCKS["service"])
    for package in ("fastapi", "uvicorn", "httpx", "pyyaml"):
        assert package in service


# --- Dockerfile -----------------------------------------------------------------------


def test_base_image_pinned_by_digest():
    base = re.search(r"^FROM\s+(\S+)", DOCKERFILE, re.M).group(1)
    assert re.fullmatch(r"python:3\.12-slim@sha256:[0-9a-f]{64}", base)


def test_all_lock_installs_require_hashes_and_wheels():
    installs = re.findall(r"pip install([^&]*?)-r /tmp/locks/requirements-(\w+)\.lock", DOCKERFILE, re.S)
    assert sorted(name for _, name in installs) == ["cisco", "service", "skillspector"]
    for flags, name in installs:
        assert "--require-hashes" in flags, name
        assert "--only-binary=:all:" in flags, name


def test_skillspector_installed_by_verified_commit():
    assert f"ARG SKILLSPECTOR_COMMIT={SKILLSPECTOR_COMMIT}" in DOCKERFILE
    assert f"ARG SKILLSPECTOR_TAG=v{SKILLSPECTOR_VERSION}" in DOCKERFILE
    assert 'test "$(git -C /tmp/skillspector rev-parse HEAD)" = "$SKILLSPECTOR_COMMIT"' in DOCKERFILE
    assert "--no-deps --no-build-isolation /tmp/skillspector" in DOCKERFILE
    # Единственная установка мимо lock -- сам SkillSpector.
    unhashed = [line for line in DOCKERFILE.splitlines() if "pip install" in line and "--require-hashes" not in line]
    assert unhashed == ["    && /opt/engines/skillspector/bin/pip install --no-deps --no-build-isolation /tmp/skillspector \\"]


def test_engine_binaries_in_env():
    assert "CISCO_BIN=/opt/engines/cisco/bin/skill-scanner" in DOCKERFILE
    assert "SKILLSPECTOR_BIN=/opt/engines/skillspector/bin/skillspector" in DOCKERFILE


# --- готовый образ ----------------------------------------------------------------------


def _docker_run(script: str) -> str:
    result = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "sh", IMAGE, "-c", script],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout


@pytest.fixture(scope="module")
def image():
    if not shutil.which("docker"):
        pytest.skip("docker не найден")
    probe = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True)
    if probe.returncode != 0:
        pytest.skip(f"образ {IMAGE} не собран (docker compose build scanner-skills)")
    return IMAGE


@pytest.mark.docker
def test_image_engine_versions(image):
    out = _docker_run(
        '$CISCO_BIN --version; /opt/engines/skillspector/bin/python -c '
        '"import importlib.metadata as m; print(m.version(\'skillspector\'))"'
    )
    assert out.split() == ["skill-scanner", CISCO_VERSION, SKILLSPECTOR_VERSION]


@pytest.mark.docker
def test_image_engines_isolated(image):
    out = _docker_run(
        "for py in /opt/service/bin/python /opt/engines/skillspector/bin/python; do "
        "$py -c 'import litellm' 2>/dev/null && echo leak-litellm; done; "
        "for py in /opt/service/bin/python /opt/engines/cisco/bin/python; do "
        "$py -c 'import langgraph' 2>/dev/null && echo leak-langgraph; done; echo done"
    )
    assert out.split() == ["done"]


@pytest.mark.docker
def test_image_service_entrypoint(image):
    out = _docker_run(
        "for c in python uvicorn git; do command -v $c; done; python -c 'import app.main' && echo import-ok"
    )
    lines = out.split()
    assert lines[:2] == ["/opt/service/bin/python", "/opt/service/bin/uvicorn"]
    assert lines[2].endswith("/git")
    assert lines[-1] == "import-ok"


@pytest.mark.docker
def test_image_engines_scan_inert_skill(image):
    """Оба движка реально отрабатывают в образе на инертном скилле."""
    skill = "---\\nname: hello\\ndescription: печатает приветствие\\n---\\n\\nВыведи echo hello.\\n"
    out = _docker_run(
        f"mkdir -p /tmp/s/hello && printf '%b' '{skill}' > /tmp/s/hello/SKILL.md && "
        "$CISCO_BIN scan /tmp/s/hello --format json --output /tmp/c.json >/dev/null 2>&1; echo cisco=$?; "
        "$SKILLSPECTOR_BIN scan /tmp/s/hello --no-llm -f json -o /tmp/k.json >/dev/null 2>&1; echo spector=$?; "
        "python -c \"import json; json.load(open('/tmp/c.json')); "
        "d=json.load(open('/tmp/k.json')); print('ok', d['execution_successful'])\""
    )
    assert "cisco=0" in out and "spector=0" in out
    assert out.strip().endswith("ok True")


# --- адаптеры движков на настоящих движках (подзадача 6) ---------------------------------

ADAPTER_SCRIPT = """
import json, sys
from pathlib import Path
from app import engines
out = {}
for name in engines.ENGINES:
    run = engines.get(name).run(Path(sys.argv[1]), workdir=Path("/tmp/runs") / name, timeout=240)
    out[name] = {"status": run.status, "error": run.error, "version": run.version, "verdict": run.own_verdict,
                 "warnings": run.warnings, "rules": sorted({f.rule_id for f in run.findings}),
                 "max": [f.severity for f in run.findings][:1]}
print(json.dumps(out))
"""


def _adapters_in_image(skill: str, *docker_args: str) -> dict:
    """Текущий код app/ (смонтирован поверх образа) гоняет настоящие движки."""
    result = subprocess.run(
        ["docker", "run", "--rm", *docker_args,
         "-v", f"{ROOT / 'app'}:/srv/app:ro",
         "-v", f"{ROOT / 'eval' / 'corpus'}:/corpus:ro",
         "--entrypoint", "python", IMAGE, "-c", ADAPTER_SCRIPT, skill],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.docker
def test_image_adapters_on_corpus_case(image):
    out = _adapters_in_image("/corpus/cisco/data-exfiltration/environment-secrets")
    assert out["cisco"]["status"] == "ok" and out["skillspector"]["status"] == "ok", out
    assert "DATA_EXFIL_SENSITIVE_FILES" in out["cisco"]["rules"]
    assert out["cisco"]["max"] == ["high"] and out["cisco"]["verdict"] == "unsafe"
    assert "PE3" in out["skillspector"]["rules"]
    assert out["cisco"]["version"] == CISCO_VERSION and out["skillspector"]["version"] == SKILLSPECTOR_VERSION


@pytest.mark.docker
def test_image_adapters_report_osv_offline(image):
    """Без сети SkillSpector берёт встроенные данные -- адаптер это видит (R-32, D-50)."""
    from app.engines.skillspector import OSV_WARNING

    out = _adapters_in_image(
        "/corpus/cisco/supply-chain-attack/unpinned-dependency", "--network", "none", "-e", "SKILLSPECTOR_OSV_TIMEOUT=3"
    )
    assert out["skillspector"]["status"] == "ok", out
    assert OSV_WARNING in out["skillspector"]["warnings"]
    assert out["cisco"]["status"] == "ok"
