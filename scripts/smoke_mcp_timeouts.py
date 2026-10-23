"""Real deadline/cleanup/orchestration checks using a harmless MCPB fixture.

No cloud calls or dependency installs. The hanging tool spawns a sleeping
fixture process which ignores TERM; the worker must kill it before reporting.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from smoke_mcp import api
from smoke_mcpb_manifest import upload


SERVER = '''import os
import signal
import subprocess
import sys
import time
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("timeout-fixture")
@mcp.tool()
def ready() -> str:
    """Return a harmless readiness marker."""
    return "timeout-fixture-ready"
@mcp.tool()
def hang() -> str:
    """Wait so that the platform can verify its execution deadline."""
    subprocess.Popen([sys.executable, "-c",
        "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(180)",
        MARKER], start_new_session=True)
    time.sleep(180)
    return "should-not-return"
if __name__ == "__main__":
    mcp.run(transport="stdio")
'''


def wait(scan_id):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        scan = api(f"/scans/{scan_id}")
        if scan["status"] not in {"pending", "running"}:
            return scan, json.loads(scan["results"])
        time.sleep(0.25)
    raise AssertionError("Scan did not terminate")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-container", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    marker = "mcp-timeout-fixture-" + uuid.uuid4().hex
    manifest = {"manifest_version": "0.3", "name": "timeout-fixture", "version": "1.0.0",
                "server": {"type": "python", "entry_point": "server.py",
                           "mcp_config": {"command": "python", "args": ["server.py"]}}}
    code, artifact = upload([("manifest.json", json.dumps(manifest)),
                             ("server.py", "MARKER = " + repr(marker) + "\n" + SERVER)])
    assert code == 200, artifact
    asset = api("/mcp-assets", {"name": "MCP timeout " + uuid.uuid4().hex[:8],
                "config": {"kind": "bundle", "artifact_id": artifact["id"]}})
    def start(name, engines, tool, timeout=8):
        job = api("/scans", {"name": name, "type": "mcp", "asset_kind": "mcp",
                  "asset_id": asset["id"], "session_id": str(uuid.uuid4()),
                  "config": {"scanner_ids": engines, "timeout_seconds": timeout,
                  "allow_tool_calls": True, "probes": [{"tool": tool, "arguments": {}}]}})
        api(f"/scans/{job['id']}/start", {})
        return job["id"]

    hanging = start("MCP timeout · middle", ["mcpradar", "mcp_dynamic", "cisco_yara"], "hang")
    neighbor = start("MCP timeout · independent", ["mcp_dynamic"], "ready", 30)
    other, other_result = wait(neighbor)
    assert other["status"] == "success", other_result
    job, result = wait(hanging)
    assert job["status"] == "partially_failed", result
    assert [(r["engine"], r["status"]) for r in result["runs"]] == [
        ("mcpradar", "success"), ("mcp_dynamic", "failed"), ("cisco_yara", "success")]
    failed = result["runs"][1]
    assert "таймаут" in failed["error"].lower() and 7 <= failed["duration_sec"] < 18, failed
    # Inspect real worker /proc only for our unique fixture marker. Do not
    # consider zombies (container init may not have reaped them yet).
    check = '''import pathlib,sys,json
needle=sys.argv[1].encode(); matches=[]
for path in pathlib.Path('/proc').glob('[0-9]*/cmdline'):
    try:
        if int(path.parent.name)==__import__('os').getpid(): continue
        if needle in path.read_bytes() and path.with_name('stat').read_text().rsplit(')',1)[1].split()[0]!='Z': matches.append(path.parent.name)
    except OSError: pass
print(json.dumps(matches))
'''
    output = subprocess.check_output(["docker", "exec", args.worker_container, "python", "-c", check, marker], text=True)
    assert json.loads(output) == [], output
    # Capacity was released, and a later run still works on the same worker.
    again = start("MCP timeout · after", ["mcp_dynamic"], "ready", 30)
    after, _ = wait(again)
    assert after["status"] == "success"
    # Catalog engines also have a total deadline, including MCP startup,
    # not merely the CLI analysis after tools/list has finished.
    slow_manifest = json.loads(json.dumps(manifest))
    slow_manifest["name"] = "slow-start-fixture"
    code, slow_artifact = upload([("manifest.json", json.dumps(slow_manifest)),
                                 ("server.py", "import time\ntime.sleep(180)\n" + SERVER)])
    assert code == 200, slow_artifact
    slow_asset = api("/mcp-assets", {"name": "MCP startup timeout " + uuid.uuid4().hex[:8],
                     "config": {"kind": "bundle", "artifact_id": slow_artifact["id"]}})
    slow_job = api("/scans", {"name": "MCP timeout · startup", "type": "mcp",
                   "asset_kind": "mcp", "asset_id": slow_asset["id"], "session_id": str(uuid.uuid4()),
                   "config": {"scanner_ids": ["cisco_yara"], "timeout_seconds": 3}})
    api(f"/scans/{slow_job['id']}/start", {})
    slow_job, slow_result = wait(slow_job["id"])
    assert slow_job["status"] == "failed" and "таймаут" in slow_result["error"].lower()
    assert 2.5 <= slow_result["duration_sec"] < 12, slow_result
    report = {"all_passed": True, "timeout_scan_id": hanging, "neighbor_scan_id": neighbor,
              "after_scan_id": again, "startup_timeout_scan_id": slow_job["id"],
              "timeout_duration_sec": failed["duration_sec"], "live_leftovers": []}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
