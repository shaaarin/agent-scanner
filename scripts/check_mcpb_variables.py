"""Check the real MCPB command builder inside a scanner container. No installs."""
import copy
from pathlib import Path
import tempfile

from app.target import stdio_command


with tempfile.TemporaryDirectory(prefix="mcpb-variables-") as tmp:
    root = Path(tmp)
    (root / "server.py").touch()
    manifest = {
        "server": {"type": "python", "entry_point": "server.py", "mcp_config": {
            "command": "${user_config.runtime}",
            "args": ["${__dirname}/server.py", "${user_config.paths}",
                     "--enabled=${user_config.enabled}", "--count=${user_config.count}",
                     "${user_config.literal}", "${user_config.default_path}"],
            "env": {"TOKEN": "${user_config.token}", "ROOT": "${__dirname}",
                    "SEP": "${pathSeparator}${/}", "HOME_PATH": "${HOME}",
                    "DOCS": "${DOCUMENTS}", "DESKTOP_PATH": "${DESKTOP}",
                    "DOWNLOADS_PATH": "${DOWNLOADS}", "LEGACY": "manifest"},
        }},
        "user_config": {"runtime": {"default": "python"},
                        "token": {"required": True},
                        "default_path": {"default": "${HOME}/config.json"}},
    }
    settings = {"token": "private-test-value", "paths": ["one space", "two;$(not-shell)"],
                "enabled": False, "count": 0, "literal": "${HOME}", "LEGACY": "asset"}
    saved = copy.deepcopy((manifest, settings))
    params = stdio_command(root, manifest, settings)
    assert params.command == "python"
    assert params.args == [str(root / "server.py"), "one space", "two;$(not-shell)",
                           "--enabled=false", "--count=0", "${HOME}", str(root / "config.json")]
    assert params.env["TOKEN"] == settings["token"]
    assert params.env["ROOT"] == params.env["HOME_PATH"] == str(root)
    assert params.env["SEP"] == "//" and params.env["DOCS"] == str(root / "Documents")
    assert params.env["DESKTOP_PATH"] == str(root / "Desktop")
    assert params.env["DOWNLOADS_PATH"] == str(root / "Downloads")
    assert params.env["LEGACY"] == "asset" and params.env["enabled"] == "False"
    assert (manifest, settings) == saved

    cases = [
        ("missing-required", {}, "обязательная настройка"),
        ("null-required", {**settings, "token": None}, "обязательная настройка"),
        ("missing-reference", {**settings, "literal": None}, "Не задана настройка"),
        ("object-reference", {**settings, "literal": {"secret": "private-test-value"}}, "ожидается"),
    ]
    for name, values, message in cases:
        try:
            stdio_command(root, manifest, values)
        except ValueError as exc:
            assert message in str(exc), (name, str(exc))
            assert "private-test-value" not in str(exc)
        else:
            raise AssertionError(name)
    for field, bad in [("args", ["${UNSUPPORTED_WORKER_SECRET}"]),
                       ("args", ["prefix=${user_config.paths}"]),
                       ("args", "not-a-list"), ("args", [1]),
                       ("env", {"KEY": "${user_config.paths}"}),
                       ("env", {"KEY": "\x00"})]:
        altered = copy.deepcopy(manifest)
        altered["server"]["mcp_config"][field] = bad
        try:
            stdio_command(root, altered, settings)
        except ValueError as exc:
            assert "private-test-value" not in str(exc)
        else:
            raise AssertionError((field, bad))
    empty_paths = {**settings, "paths": []}
    assert len(stdio_command(root, manifest, empty_paths).args) == len(params.args) - 2
    legacy = {"server": {"type": "python", "entry_point": "server.py",
                         "mcp_config": {"command": "python", "args": ["server.py"]}}}
    assert stdio_command(root, legacy).args == ["server.py"]
    print("MCPB substitutions: command/args/env, defaults, paths, lists, scalar values, "
          "single-pass safety, validation and legacy compatibility OK")
