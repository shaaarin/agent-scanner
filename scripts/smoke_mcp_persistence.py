"""Real control-api outage on an ISOLATED Compose test stand only.

Temporarily stops control-api and pauses the dynamic worker; restores both
in finally. Requires the normal smoke MCP target. Leaves its test records.
Never use on a shared/production stack. No worker calls are mocked.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from smoke_mcp import api


def wait_for(fn, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(0.3)
    raise AssertionError("Timed out waiting for test state")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose-file", type=Path, required=True)
    parser.add_argument("--mode", choices=["recovered", "exhausted"], default="recovered")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    compose = ["docker-compose", "-f", str(args.compose_file.resolve())]

    def docker(*cmd):
        return subprocess.check_output(compose + list(cmd), text=True, stderr=subprocess.STDOUT)

    def healthy():
        try:
            return api("/health")["status"] == "ok"
        except Exception:
            return False

    assert not api("/scans?status=running"), "Other scans are running; won't stop the API"
    asset = api("/mcp-assets", {"name": "MCP persistence " + uuid.uuid4().hex[:8],
        "config": {"kind": "remote", "server_url": os.getenv("MCP_TEST_TARGET", "http://mcp-test-target:8000/mcp")}})
    job = api("/scans", dict(name="MCP persistence · " + args.mode, type="mcp",
        asset_kind="mcp", asset_id=asset["id"], session_id=str(uuid.uuid4()),
        config={"scanner_ids": ["cisco_yara", "mcp_dynamic", "cisco_readiness"], "timeout_seconds": 30}))
    scan_id = job["id"]
    since = datetime.now(timezone.utc).isoformat()
    dynamic_paused = False
    try:
        docker("pause", "scanner-mcp-mcp-dynamic")
        dynamic_paused = True
        api(f"/scans/{scan_id}/start", {})

        def waiting_on_dynamic():
            scan = api(f"/scans/{scan_id}")
            result = json.loads(scan.get("results") or "{}")
            logs = api(f"/scans/{scan_id}/logs")
            return scan if result.get("summary", {}).get("completed") == 1 and any(
                line["message"] == "Выполняется mcp_dynamic" for line in logs) else None

        before = wait_for(waiting_on_dynamic, 20)
        docker("stop", "control-api")
        docker("unpause", "scanner-mcp-mcp-dynamic")
        dynamic_paused = False

        def retry_seen():
            logs = docker("logs", "--no-color", "--since", since, "scanner-mcp")
            needle = f"PATCH /scans/{scan_id}:" if args.mode == "recovered" else f"POST /scans/{scan_id}/logs:"
            return logs if needle in logs and (args.mode == "exhausted" or "retry 3/5" in logs) else None

        retry_log = wait_for(retry_seen, 55)
        docker("start", "control-api")
        wait_for(healthy)

        def finished():
            scan = api(f"/scans/{scan_id}")
            return scan if scan["status"] not in ("pending", "running") else None

        after = wait_for(finished)
        result = json.loads(after["results"])
        previous = json.loads(before["results"])
        assert result["runs"][0] == previous["runs"][0], "Previous checkpoint changed/lost"
        count = 3 if args.mode == "recovered" else 2
        assert after["status"] == ("success" if count == 3 else "partially_failed")
        assert result["summary"] == dict(total=3, completed=count, failed=0, pending=3-count)
        assert [r["engine"] for r in result["runs"]] == ["cisco_yara", "mcp_dynamic", "cisco_readiness"][:count]
        assert all(r["status"] == "success" for r in result["runs"])
        assert result["runs"][1]["tools_checked"] == 3, "Newest (unsaved) result was lost"
        logs = api(f"/scans/{scan_id}/logs")
        assert sum(line["message"] == "Выполняется mcp_dynamic" for line in logs) == 1
        if args.mode == "recovered":
            assert any(line["message"].startswith("Завершён cisco_readiness") for line in logs)
        else:
            assert after["error"] and any(line["phase"] == "Ошибка" for line in logs)
        executions = {}
        for engine in ("cisco_yara", "mcp_dynamic", "cisco_readiness"):
            worker_log = docker("logs", "--no-color", "--since", since,
                                "scanner-mcp-" + engine.replace("_", "-"))
            executions[engine] = worker_log.count('"POST /execute ')
            expected = 0 if args.mode == "exhausted" and engine == "cisco_readiness" else 1
            assert executions[engine] == expected, (engine, executions[engine])
        report = dict(passed=True, mode=args.mode, scan_id=scan_id, before=before,
                      after=after, logs=logs, retry_log=retry_log, worker_executions=executions)
        if args.output:
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(dict(passed=True, mode=args.mode, scan_id=scan_id, summary=result["summary"])))
    finally:
        # Restore even if an assertion or interruption aborted the scenario.
        try:
            if dynamic_paused:
                docker("unpause", "scanner-mcp-mcp-dynamic")
        finally:
            docker("start", "control-api")
            wait_for(healthy)


if __name__ == "__main__":
    main()
