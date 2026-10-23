"""Live MCP orchestration checks. No mocks, cloud calls or fixture deletion."""
import argparse
import json
import os
from pathlib import Path
import time
import uuid

from smoke_mcp import api


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-readiness-down", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    asset = api("/mcp-assets", {
        "name": "MCP isolation " + uuid.uuid4().hex[:8],
        "config": {"kind": "remote", "transport": "streamable_http",
                   "server_url": os.getenv("MCP_TEST_TARGET", "http://mcp-test-target:8000/mcp")},
    })
    defaults = ["cisco_yara", "cisco_readiness", "cisco_prompt_defense", "mcp_dynamic"]
    cases = [
        ("middle", ["cisco_yara", "cisco_readiness", "mcp_dynamic"]),
        ("first", ["cisco_readiness", "cisco_yara"]),
        ("last", ["cisco_yara", "cisco_readiness"]),
        ("defaults", []),
        ("single-readiness", ["cisco_readiness"]),
        ("single-dynamic", ["mcp_dynamic"]),
        ("finding-not-error", ["mcp_dynamic"]),
    ]
    reports = []
    for name, ids in cases:
        config = {"scanner_ids": ids, "timeout_seconds": 30}
        if name == "finding-not-error":
            config.update(allow_tool_calls=True, probes=[{
                "tool": "echo", "arguments": {"text": "actual"}, "contains": "missing-marker",
            }])
        job = api("/scans", {"name": "MCP isolation · " + name, "type": "mcp",
            "asset_kind": "mcp", "asset_id": asset["id"],
            "session_id": "isolation-" + uuid.uuid4().hex, "config": config})
        row = {"case": name, "scan_id": job["id"], "passed": False, "snapshots": []}
        reports.append(row)
        try:
            api(f"/scans/{job['id']}/start", {})
            deadline = time.monotonic() + 150
            previous = []
            while time.monotonic() < deadline:
                job = api(f"/scans/{job['id']}")
                result = json.loads(job.get("results") or "{}")
                if result:
                    runs = result.get("runs", [result])
                    # Single-result summary is additional aggregate metadata.
                    comparable = [{k: v for k, v in r.items() if k != "summary"} for r in runs]
                    assert comparable[:len(previous)] == previous, "Previously saved results changed/lost"
                    previous = comparable
                    snapshot = {"scan_status": job["status"], "summary": result["summary"],
                                "runs": [{"engine": r["engine"], "status": r["status"]} for r in runs]}
                    if not row["snapshots"] or row["snapshots"][-1] != snapshot:
                        row["snapshots"].append(snapshot)
                if job["status"] in ("success", "partially_failed", "failed"):
                    break
                time.sleep(0.15)
            row.update(job=job, logs=api(f"/scans/{job['id']}/logs"))
            expected = ids or defaults
            runs = result.get("runs", [result])
            assert [r["engine"] for r in runs] == expected
            failed = 0
            for r in runs:
                should_fail = args.expect_readiness_down and r["engine"] == "cisco_readiness"
                assert r["status"] == ("failed" if should_fail else "success"), r
                if should_fail:
                    failed += 1
                    assert r["error"] and r["findings"] == []
                if r["engine"] == "cisco_yara":
                    assert r["findings"], "Real test target poisoning must be detected"
                if r["engine"] == "mcp_dynamic":
                    assert r["checks"] and r["tools_checked"] == 3
            assert result["summary"] == dict(total=len(expected), completed=len(expected)-failed, failed=failed, pending=0)
            expected_status = "failed" if failed == len(expected) else "partially_failed" if failed else "success"
            assert job["status"] == expected_status, job.get("error") or job["status"]
            assert result["status"] == expected_status
            if len(expected) > 1:
                assert result["findings"] == [f for r in runs for f in r["findings"]]
            if name == "finding-not-error":
                assert result["findings"] and any(c["status"] == "failed" for c in result["checks"])
            row["passed"] = True
        except Exception as exc:
            row["error"] = str(exc)
    report = dict(asset_id=asset["id"], all_passed=all(r["passed"] for r in reports), results=reports)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text)
        print(json.dumps({"all_passed": report["all_passed"], "results": [
            {k: r[k] for k in ("case", "scan_id", "passed", "error") if k in r}
            for r in reports]}, ensure_ascii=False, indent=2))
    else:
        print(text)
    raise SystemExit(0 if report["all_passed"] else 1)


if __name__ == "__main__":
    main()
