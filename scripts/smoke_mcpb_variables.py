"""Live MCPB substitutions through upload, saved scan config and real workers.

Only our harmless self-contained FastMCP fixture; no installs or cloud calls.
Leaves test assets/scans for inspection. MCP_TEST_API sets API URL.
"""
import argparse
import copy
import json
from pathlib import Path
import time
import uuid

from smoke_mcp import api
from smoke_mcpb_manifest import upload


SERVER = '''import os
import sys
from pathlib import Path
from mcp.server.fastmcp import FastMCP

root = Path(__file__).resolve().parent
assert sys.argv[1:] == ["one space", "two;$(not-shell)", "--enabled=false", "--count=0", "${HOME}"]
assert os.environ["TOKEN"] == "private-template-fixture"
assert os.environ["DEFAULT_PATH"] == str(root / "config.json")
assert os.environ["BUNDLE_ROOT"] == str(root)
assert os.environ["BOOL"] == "false" and os.environ["NUMBER"] == "0"
mcp = FastMCP("bundle-template-fixture")
@mcp.tool()
def ready() -> str:
    """Confirm that command arguments and environment matched the fixture."""
    return "template-fixture-ready"
if __name__ == "__main__":
    mcp.run(transport="stdio")
'''
MANIFEST = {
    "manifest_version": "0.3", "name": "template-fixture", "version": "1.0.0",
    "server": {"type": "python", "entry_point": "server.py", "mcp_config": {
        "command": "${user_config.runtime}",
        "args": ["${__dirname}/server.py", "${user_config.folders}",
                 "--enabled=${user_config.enabled}", "--count=${user_config.count}", "${user_config.literal}"],
        "env": {"TOKEN": "${user_config.token}", "DEFAULT_PATH": "${user_config.default_path}",
                "BUNDLE_ROOT": "${__dirname}", "BOOL": "${user_config.enabled}",
                "NUMBER": "${user_config.count}"},
    }},
    "user_config": {"runtime": {"default": "python"}, "token": {"required": True},
                    "default_path": {"default": "${HOME}/config.json"}},
}
SETTINGS = {"token": "private-template-fixture", "folders": ["one space", "two;$(not-shell)"],
            "enabled": False, "count": 0, "literal": "${HOME}"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    reports = []
    unknown = copy.deepcopy(MANIFEST)
    unknown["server"]["mcp_config"]["args"].append("${UNSUPPORTED_WORKER_SECRET}")
    for name, manifest, settings, engines, expected in [
        ("templates-all-local", MANIFEST, SETTINGS,
         ["semgrep", "mcpradar", "cisco_yara", "cisco_readiness", "cisco_prompt_defense", "mcp_dynamic"], "success"),
        ("missing-required", MANIFEST, {}, ["mcp_dynamic"], "failed"),
        ("unknown-variable", unknown, SETTINGS, ["mcp_dynamic"], "failed"),
    ]:
        code, artifact = upload([("manifest.json", json.dumps(manifest)), ("server.py", SERVER)])
        assert code == 200, artifact
        asset = api("/mcp-assets", {"name": "MCPB templates " + name + " " + uuid.uuid4().hex[:8],
                    "config": {"kind": "bundle", "artifact_id": artifact["id"], "user_config": settings}})
        scan = api("/scans", {"name": "MCPB · " + name, "type": "mcp", "asset_kind": "mcp",
                   "asset_id": asset["id"], "session_id": str(uuid.uuid4()),
                   "config": {"scanner_ids": engines, "timeout_seconds": 60, "allow_tool_calls": True,
                              "probes": [{"tool": "ready", "arguments": {}, "contains": "template-fixture-ready"}]}})
        assert json.loads(scan["config"])["target"]["user_config"] == settings
        api(f"/scans/{scan['id']}/start", {})
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            scan = api(f"/scans/{scan['id']}")
            if scan["status"] not in {"pending", "running"}:
                break
            time.sleep(1)
        result = json.loads(scan.get("results") or "{}")
        assert scan["status"] == expected, (scan["id"], result)
        if expected == "success":
            assert [r["engine"] for r in result["runs"]] == engines
            assert all(r["status"] == "success" for r in result["runs"])
            dynamic = result["runs"][-1]
            assert dynamic["tools_checked"] == 1 and all(c["status"] == "passed" for c in dynamic["checks"])
        else:
            message = result.get("error", "")
            assert ("обязательная настройка" if name == "missing-required" else "Неподдерживаемая переменная") in message
        logs = api(f"/scans/{scan['id']}/logs")
        assert SETTINGS["token"] not in json.dumps([result, logs])
        reports.append({"case": name, "scan_id": scan["id"], "status": scan["status"], "passed": True})
    report = json.dumps({"all_passed": True, "results": reports}, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(report)
    print(report)


if __name__ == "__main__":
    main()
