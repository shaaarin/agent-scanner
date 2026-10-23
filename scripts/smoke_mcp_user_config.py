"""Live MCPB user_config checks. Runs only a harmless, self-contained fixture.

Requires the MCP coordinator and local workers. No installs or cloud calls.
Leaves test artifacts/assets/scans for inspection. MCP_TEST_API overrides API.
"""
import argparse
import io
import json
from pathlib import Path
import time
import urllib.request
import uuid
import zipfile

from smoke_mcp import BASE, api


SERVER = '''import os
from mcp.server.fastmcp import FastMCP

if os.environ.get("SMOKE_REQUIRE_CONFIG") == "1":
    expected = {"SMOKE_TEXT": "configured-value", "SMOKE_ZERO": "0",
                "SMOKE_BOOL": "False", "SMOKE_NUMBER": "1.5"}
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Required fixture configuration missing or incorrect")

mcp = FastMCP("bundle-user-config-fixture")

@mcp.tool()
def ready() -> str:
    """Report successful startup without returning configuration values."""
    return "fixture-ready"

if __name__ == "__main__":
    mcp.run(transport="stdio")
'''
CONFIG = {"SMOKE_TEXT": "configured-value", "SMOKE_ZERO": 0,
          "SMOKE_BOOL": False, "SMOKE_NUMBER": 1.5}
ENGINES = ["mcpradar", "cisco_yara", "cisco_readiness", "cisco_prompt_defense", "mcp_dynamic"]


def upload(required):
    manifest = dict(manifest_version="0.3", name="user-config-fixture", version="1.0.0",
        server=dict(type="python", entry_point="server.py", mcp_config=dict(
            command="python", args=["server.py"], env={
                "SMOKE_REQUIRE_CONFIG": "1" if required else "0",
                "SMOKE_TEXT": "manifest-default",  # asset settings must override it
            })))
    archive_data = io.BytesIO()
    with zipfile.ZipFile(archive_data, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("server.py", SERVER)
    boundary = "mcp-user-config-" + uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="fixture.mcpb"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n').encode()
    body += archive_data.getvalue() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(BASE + "/mcp-artifacts/upload", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def run_case(name, artifact, user_config, engines, expected_status):
    target = {"kind": "bundle", "artifact_id": artifact["id"]}
    if user_config is not None:
        target["user_config"] = user_config
    asset = api("/mcp-assets", {"name": name + " " + uuid.uuid4().hex[:8], "config": target})
    job = api("/scans", dict(name=name, type="mcp", asset_kind="mcp", asset_id=asset["id"],
        session_id=str(uuid.uuid4()), config=dict(scanner_ids=engines, timeout_seconds=30,
            allow_tool_calls=True, probes=[dict(tool="ready", arguments={}, contains="fixture-ready")])))
    assert json.loads(job["config"])["target"]["user_config"] == (user_config or {})
    api(f"/scans/{job['id']}/start", {})
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        job = api(f"/scans/{job['id']}")
        if job["status"] not in {"pending", "running"}:
            break
        time.sleep(1)
    result = json.loads(job.get("results") or "{}")
    assert job["status"] == expected_status, (job["id"], job["status"], result)
    if expected_status == "success":
        runs = result.get("runs", [result])
        assert [r["engine"] for r in runs] == engines
        assert all(r["status"] == "success" and r["tools_checked"] == 1 for r in runs)
        dynamic = next(r for r in runs if r["engine"] == "mcp_dynamic")
        assert len(dynamic["checks"]) == 3 and all(c["status"] == "passed" for c in dynamic["checks"])
    logs = api(f"/scans/{job['id']}/logs")
    assert CONFIG["SMOKE_TEXT"] not in json.dumps([result, logs]), "Fixture config leaked into report/log"
    return dict(case=name, scan_id=job["id"], asset_id=asset["id"], passed=True,
                status=job["status"], summary=result.get("summary"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expect-unfixed", action="store_true", help="Reproduce the lost-config bug before the fix")
    args = parser.parse_args()
    required = upload(True)
    reports = []
    if args.expect_unfixed:
        reports.append(run_case("MCPB · user_config до исправления", required, CONFIG, ["mcp_dynamic"], "failed"))
    else:
        reports.append(run_case("MCPB · user_config всем движкам", required, CONFIG, ENGINES, "success"))
        reports.append(run_case("MCPB · обязательный конфиг отсутствует", required, {}, ["mcp_dynamic"], "failed"))
        optional = upload(False)
        reports.append(run_case("MCPB · пустой user_config", optional, {}, ["mcp_dynamic"], "success"))
        reports.append(run_case("MCPB · user_config не задан", optional, None, ["mcp_dynamic"], "success"))
    report = dict(all_passed=True, expect_unfixed=args.expect_unfixed, results=reports)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(output)
    print(output)


if __name__ == "__main__":
    main()
