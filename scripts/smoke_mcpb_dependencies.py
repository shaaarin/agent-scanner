"""Upload safe MCPBs with local wheels and scan with real runtime workers.

No external downloads: each fixture installs its own tiny wheel via --no-index.
Leaves test assets/scans for inspection. MCP_TEST_API sets API URL.
"""
import argparse
import json
from pathlib import Path
import time
import uuid

from smoke_mcp import api
from smoke_mcpb_manifest import upload
from check_mcpb_dependencies import fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    jobs = []
    engines = ["mcpradar", "cisco_yara", "cisco_readiness", "cisco_prompt_defense", "mcp_dynamic"]
    for marker in ["bundle-A", "bundle-B"]:
        code, artifact = upload(fixture(marker))
        assert code == 200, artifact
        asset = api("/mcp-assets", {"name": "MCPB dependencies " + marker + " " + uuid.uuid4().hex[:8],
                    "config": {"kind": "bundle", "artifact_id": artifact["id"]}})
        scan = api("/scans", {"name": "MCPB · dependencies · " + marker,
                   "type": "mcp", "asset_kind": "mcp", "asset_id": asset["id"],
                   "session_id": str(uuid.uuid4()), "config": {"scanner_ids": engines,
                   "timeout_seconds": 120, "allow_tool_calls": True,
                   "probes": [{"tool": "ready", "arguments": {}, "contains": marker}]}})
        api(f"/scans/{scan['id']}/start", {})
        jobs.append(scan)
    reports = []
    deadline = time.monotonic() + 300
    for scan in jobs:
        while time.monotonic() < deadline:
            scan = api(f"/scans/{scan['id']}")
            if scan["status"] not in {"pending", "running"}:
                break
            time.sleep(1)
        result = json.loads(scan.get("results") or "{}")
        assert scan["status"] == "success", (scan["id"], result)
        assert [r["engine"] for r in result["runs"]] == engines
        assert all(r["status"] == "success" and r["tools_checked"] == 1 for r in result["runs"])
        assert all(c["status"] == "passed" for c in result["runs"][-1]["checks"])
        reports.append({"scan_id": scan["id"], "passed": True, "summary": result["summary"]})
    output = json.dumps({"all_passed": True, "results": reports}, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(output)
    print(output)


if __name__ == "__main__":
    main()
