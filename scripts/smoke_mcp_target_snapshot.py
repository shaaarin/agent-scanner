"""Real API checks: asset-only target, immutable scan snapshot and retry modes.

Changes only its own fixture asset. No cloud calls or external downloads.
"""
import argparse
import json
import os
from pathlib import Path
import time
import uuid

from smoke_mcp import api
from smoke_mcp_retries import request


def wait(scan_id, expected):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        scan = api(f"/scans/{scan_id}")
        if scan["status"] not in {"pending", "running"}:
            assert scan["status"] == expected, scan
            return scan
        time.sleep(0.2)
    raise AssertionError(f"Scan {scan_id} did not terminate")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    original = {"kind": "remote", "server_url": os.getenv("MCP_TEST_TARGET", "http://mcp-test-target:8000/mcp"),
                "transport": "streamable_http", "headers": {"X-Snapshot-Fixture": "original"}, "verify_tls": True}
    asset = api("/mcp-assets", {"name": "MCP snapshot " + uuid.uuid4().hex[:8], "config": original})
    original = asset["config"]
    changed = {**original, "server_url": original["server_url"].rstrip("/") + "/missing-snapshot-fixture",
               "headers": {"X-Snapshot-Fixture": "edited"}, "transport": "sse"}
    params = {"scanner_ids": ["mcp_dynamic"], "timeout_seconds": 30}
    def create(config):
        return {"name": "MCP · target snapshot", "type": "mcp", "asset_kind": "mcp",
                "asset_id": asset["id"], "session_id": str(uuid.uuid4()), "config": config}

    before_ids = {scan["id"] for scan in api(f"/scans?asset_kind=mcp&asset_id={asset['id']}")}
    rejected = []
    for target in [changed, original, {}, None, {"kind": "bundle", "artifact_id": 1},
                   {"kind": "repository", "git_repo_url": "https://example.com/other.git"}]:
        code, error = request("/scans", create({**params, "target": target}))
        assert code == 422 and "config.target" in error["detail"], (code, error)
        rejected.append(code)
    after_ids = {scan["id"] for scan in api(f"/scans?asset_kind=mcp&asset_id={asset['id']}")}
    assert after_ids == before_ids, "Rejected overrides must not create scan rows"

    good = api("/scans", create(params))
    bad_params = {**params, "allow_tool_calls": True,
                  "probes": [{"tool": "missing_snapshot_fixture_tool", "arguments": {}}]}
    bad = api("/scans", create(bad_params))
    for scan, expected in [(good, params), (bad, bad_params)]:
        saved = json.loads(scan["config"])
        assert saved["target"] == original
        assert all(saved[key] == value for key, value in expected.items())
    code, edited = request(f"/mcp-assets/{asset['id']}", {"config": changed}, method="PUT")
    assert code == 200 and edited["config"] == changed, edited
    newer = api("/scans", create(params))
    assert json.loads(newer["config"])["target"] == changed

    reports = []
    for source, status in [(good, "success"), (bad, "failed")]:
        api(f"/scans/{source['id']}/start", {})
        finished = wait(source["id"], status)
        assert json.loads(finished["config"])["target"] == original
        before = {key: finished[key] for key in ("config", "results", "status")}
        modes = ["engine"] if status == "success" else ["all", "failed"]
        for mode in modes:
            payload = {"mode": mode}
            if mode == "engine":
                payload["engine_id"] = "mcp_dynamic"
            attempt = api(f"/scans/{source['id']}/retry", payload)
            assert json.loads(attempt["config"])["target"] == original
            assert attempt["retry_of_scan_id"] == source["id"]
            finished_retry = wait(attempt["id"], status)
            reports.append({"mode": mode, "scan_id": finished_retry["id"], "status": status, "passed": True})
        unchanged = api(f"/scans/{source['id']}")
        assert {key: unchanged[key] for key in before} == before
    output = json.dumps({"all_passed": True, "asset_id": asset["id"], "rejected_overrides": len(rejected),
        "source_scan_id": good["id"], "failed_scan_id": bad["id"], "new_snapshot_scan_id": newer["id"],
        "retries": reports}, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(output)
    print(output)


if __name__ == "__main__":
    main()
