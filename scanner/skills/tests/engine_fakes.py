"""Подставные CLI движков для тестов: настоящий исполняемый файл, который
принимает те же аргументы и пишет отчёт туда, куда сказали. Отчёты --
настоящие JSON движков из `fixtures/engines/`. Это не мок LLM: LLM в MVP
нет вообще (D-37), а сами движки проверяются в образе (`test_image.py`)."""
import sys
import textwrap
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "engines"

BIN_ENV = {"cisco": "CISCO_BIN", "skillspector": "SKILLSPECTOR_BIN"}

# Тело подставного движка. Доступны: args, output (Path), skill_dir (Path).
WRITE_FIXTURE = "output.write_text(Path({fixture!r}).read_text())"


def install(tmp_path: Path, monkeypatch, engine: str, body: str, *, stderr: str = "") -> Path:
    """Создаёт исполняемый файл движка `engine` и прописывает его в *_BIN."""
    script = tmp_path / f"fake-{engine}"
    script.write_text(
        f"#!{sys.executable}\n"
        + textwrap.dedent(
            f"""
            import json, sys, time
            from pathlib import Path
            args = sys.argv[1:]
            flag = "--output" if "--output" in args else "-o"
            output = Path(args[args.index(flag) + 1])
            skill_dir = Path(args[1])
            sys.stderr.write({stderr!r})
            """
        )
        + textwrap.dedent(body)
        + "\n"
    )
    script.chmod(0o755)
    monkeypatch.setenv(BIN_ENV[engine], str(script))
    return script


def fixture_body(name: str) -> str:
    return WRITE_FIXTURE.format(fixture=str(FIXTURES / name))


def install_fixture(tmp_path, monkeypatch, engine: str, name: str, **kw) -> Path:
    return install(tmp_path, monkeypatch, engine, fixture_body(name), **kw)


def offline_stderr() -> str:
    return (FIXTURES / "skillspector-unpinned-offline.stderr").read_text()
