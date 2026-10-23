"""Live retry checks against an isolated local Compose stand.

Temporarily stops/starts readiness and coordinator containers, restoring them
in finally. No mocks, cloud calls or dependency installs. Leaves the test
assets, attempts and logs for inspection. Do not run against a shared stand.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid

from smoke_mcp import BASE, REMOTE, TOOLS, api, make_asset
from smoke_mcpb_manifest import MANIFEST, upload

SLOW_SERVER = '''import time
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("retry-fixture")
@mcp.tool()
def wait_ready() -> str:
    """Wait four seconds, then report readiness. No external side effects."""
    time.sleep(4)
    return "fixture-ready"
if __name__ == "__main__":
    mcp.run(transport="stdio")
'''


def request(path, data=None, method="POST"):
    req = urllib.request.Request(BASE + path, method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            return exc.code, json.loads(body)
        except ValueError:
            return exc.code, {"detail": body}


def wait_job(job, status):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        job = api(f"/scans/{job['id']}")
        if job["status"] not in {"pending", "running"}:
            assert job["status"] == status, job
            return job
        time.sleep(0.2)
    raise AssertionError(f"Timeout: {job['id']}")


def outcomes(job):
    report = json.loads(job["results"] or "{}")
    return report.get("runs", [report])


def create(asset, ids, **params):
    return api("/scans", dict(name="Повторные запуски · smoke", type="mcp",
        asset_kind="mcp", asset_id=asset["id"], session_id=str(uuid.uuid4()),
        config=dict(scanner_ids=ids, timeout_seconds=30, **params)))


def retry(source, mode="all", engine_id=None):
    payload = dict(mode=mode)
    if engine_id is not None:
        payload["engine_id"] = engine_id
    code, attempt = request(f"/scans/{source['id']}/retry", payload)
    assert code == 200, (code, attempt)
    assert attempt["id"] != source["id"] and attempt["retry_of_scan_id"] == source["id"]
    assert attempt["retry_root_scan_id"] == (source["retry_root_scan_id"] or source["id"])
    assert attempt["session_id"] != source["session_id"]
    assert all(attempt[key] is None for key in ("agent_namespace", "agent_pod_name", "build_job_name", "built_image"))
    return attempt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose-file", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    compose = ([shutil.which("docker-compose")] if shutil.which("docker-compose") else ["docker", "compose"])
    compose += ["-f", str(args.compose_file.resolve())]
    reports = []

    def docker(*command):
        result = subprocess.run(compose + list(command), text=True, capture_output=True, timeout=50)
        assert result.returncode == 0, result.stderr

    def start(service):
        docker("start", service)
        # Wait for the actual process, not just the container running state.
        for _ in range(40):
            result = subprocess.run(compose + ["exec", "-T", service, "python", "-c",
                "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=1)"],
                capture_output=True, timeout=10)
            if result.returncode == 0:
                return
            time.sleep(0.25)
        raise AssertionError(f"Service not ready: {service}")

    def passed(case, **data):
        reports.append(dict(case=case, passed=True, **data))
        print(f"PASS: {case}", flush=True)

    def rejected(source, payload, status):
        code, result = request(f"/scans/{source['id']}/retry", payload)
        assert code == status, (code, result)

    try:
        docker("stop", "scanner-mcp-cisco-readiness")
        asset = make_asset("retry", REMOTE)
        source = create(asset, ["cisco_yara", "cisco_readiness", "mcp_dynamic"], allow_tool_calls=True,
                        probes=[dict(tool="echo", arguments={"text": "actual"}, contains="missing-marker")])
        api(f"/scans/{source['id']}/start", {})
        source = wait_job(source, "partially_failed")
        old_logs = api(f"/scans/{source['id']}/logs")
        assert [r["status"] for r in outcomes(source)] == ["success", "failed", "success"]
        assert outcomes(source)[2]['findings'], "A failed probe is a finding, not a failed engine"
        # Change only our disposable asset. Retries must keep the scan snapshot.
        code, response = request(f"/mcp-assets/{asset['id']}", {"config": {"kind": "snapshot", "tools": TOOLS}}, "PUT")
        assert code == 200, response
        full = wait_job(retry(source), "partially_failed")
        assert json.loads(full["config"]) == json.loads(source["config"])
        assert len(outcomes(full)) == 3
        passed("full-retry-preserves-target-snapshot", source_id=source["id"], scan_id=full["id"])
        failed = wait_job(retry(source, "failed"), "failed")
        assert json.loads(failed["config"])["scanner_ids"] == ["cisco_readiness"]
        assert len(outcomes(failed)) == 1
        passed("failed-only-does-not-rerun-successful-engines", scan_id=failed["id"])

        defaults = create(make_asset("retry-defaults", REMOTE), [])
        api(f"/scans/{defaults['id']}/start", {})
        defaults = wait_job(defaults, "partially_failed")
        defaults_retry = wait_job(retry(defaults), "partially_failed")
        assert json.loads(defaults_retry["config"])["scanner_ids"] == []
        default_failed = wait_job(retry(defaults, "failed"), "failed")
        assert json.loads(default_failed["config"])["scanner_ids"] == ["cisco_readiness"]
        passed("empty-selection-full-and-failed-only", scan_id=defaults_retry["id"])

        # Exercise compatibility using our real report in its historical
        # completed representation; no upstream response is substituted.
        code, legacy = request(f"/scans/{defaults['id']}", {"status": "completed"}, "PATCH")
        assert code == 200
        legacy_options = api(f"/scans/{legacy['id']}/retries")
        assert legacy_options['can_retry_all'] and legacy_options['can_retry_failed']
        assert legacy_options['attempts'][0]['status'] == 'partially_failed'
        legacy_retry = wait_job(retry(legacy, 'failed'), 'failed')
        assert json.loads(legacy_retry['config'])['scanner_ids'] == ['cisco_readiness']
        passed("historical-completed-report", scan_id=legacy_retry['id'])

        rejected(source, {"mode": "engine", "engine_id": "semgrep"}, 422)
        rejected(source, {"mode": "engine"}, 422)
        rejected(source, {"mode": "all", "engine_id": "cisco_yara"}, 422)
        rejected(source, {"mode": "unexpected"}, 422)
        rejected(source, {"mode": "all", "config": {}}, 422)
        assert request('/scans/2147483647/retry', {"mode": "all"})[0] == 404
        pending = create(asset, ["cisco_yara"])
        rejected(pending, {"mode": "all"}, 409)
        rejected(pending, {"mode": "engine", "engine_id": "cisco_yara"}, 409)
        passed("invalid-requests-and-pending-scan-rejected")

        start("scanner-mcp-cisco-readiness")
        recovered = wait_job(retry(failed), "success")
        assert len(outcomes(recovered)) == 1 and outcomes(recovered)[0]["engine"] == "cisco_readiness"
        rejected(recovered, {"mode": "all"}, 409)
        rejected(recovered, {"mode": "failed"}, 409)
        single = wait_job(retry(recovered, "engine", "cisco_readiness"), "success")
        passed("recovery-and-individual-engine-from-success", scan_id=single["id"])
        assert api(f"/scans/{source['id']}") == source
        assert api(f"/scans/{source['id']}/logs") == old_logs
        assert request(f"/scans/{source['id']}", method="DELETE")[0] == 409
        history = api(f"/scans/{single['id']}/retries")["attempts"]
        assert {s["id"] for s in history} == {source['id'], full['id'], failed['id'], recovered['id'], single['id']}
        assert request(f"/scans/{single['id']}", method="DELETE")[0] == 200
        assert single['id'] not in {s['id'] for s in api(f"/scans/{source['id']}/retries")['attempts']}
        passed("history-original-logs-and-delete-guards", source_id=source['id'])

        code, artifact = upload([("manifest.json", json.dumps(MANIFEST)), ("server.py", SLOW_SERVER)])
        assert code == 200
        bundle = make_asset("retry-bundle", {"kind": "bundle", "artifact_id": artifact['id'], "user_config": {"FIXTURE": "retry-value"}})
        slow = create(bundle, ["mcp_dynamic"], allow_tool_calls=True,
                      probes=[dict(tool="wait_ready", arguments={}, contains="fixture-ready")])
        api(f"/scans/{slow['id']}/start", {})
        slow = wait_job(slow, "success")
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: request(f"/scans/{slow['id']}/retry", {"mode": "engine", "engine_id": "mcp_dynamic"}), range(2)))
        assert sorted(code for code, _ in responses) == [200, 409], responses
        concurrent = next(job for code, job in responses if code == 200)
        assert request(f"/scans/{concurrent['id']}", method="DELETE")[0] == 409
        assert request(f"/scans/{concurrent['id']}/start", {})[0] == 400
        rejected(concurrent, {"mode": "all"}, 409)
        assert api(f"/scans/{slow['id']}/retries")['active_scan_id'] == concurrent['id']
        concurrent = wait_job(concurrent, "success")
        assert json.loads(concurrent['config']) == json.loads(slow['config'])
        assert outcomes(concurrent)[0]['tools_checked'] == 1
        passed("concurrent-retry-and-running-guards", scan_id=concurrent['id'])

        interrupted = create(bundle, ["cisco_yara", "mcp_dynamic", "cisco_readiness"], allow_tool_calls=True,
                             probes=[dict(tool="wait_ready", arguments={}, contains="fixture-ready")])
        api(f"/scans/{interrupted['id']}/start", {})
        for _ in range(200):
            partial = api(f"/scans/{interrupted['id']}")
            result = json.loads(partial.get('results') or '{}')
            if result.get('summary', {}).get('completed') == 1:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("No intermediate checkpoint")
        docker("stop", "-t", "1", "scanner-mcp")
        start("scanner-mcp")
        interrupted = wait_job(interrupted, "partially_failed")
        options = api(f"/scans/{interrupted['id']}/retries")
        assert [e['id'] for e in options['engines'] if e['status'] != 'success'] == ['mcp_dynamic', 'cisco_readiness']
        resumed = wait_job(retry(interrupted, 'failed'), 'success')
        assert [r['engine'] for r in outcomes(resumed)] == ['mcp_dynamic', 'cisco_readiness']
        assert api(f"/scans/{interrupted['id']}") == interrupted
        passed("retry-unfinished-engines-after-coordinator-restart", source_id=interrupted['id'], scan_id=resumed['id'])

        docker("stop", "-t", "1", "scanner-mcp")
        dispatch_failed = wait_job(retry(source), "failed")
        assert dispatch_failed['results'] is None and dispatch_failed['error']
        assert api(f"/scans/{source['id']}") == source
        start("scanner-mcp")
        dispatch_recovered = wait_job(retry(dispatch_failed), "success")
        assert len(outcomes(dispatch_recovered)) == 3
        passed("dispatch-failure-is-separate-retryable-attempt", scan_id=dispatch_recovered['id'])

        # General scan-level retry also works for other scanner types. This
        # stand has no DeepTeam service: both dispatches must fail before LLM.
        agent = api('/agent-configs', dict(name='retry-agent-' + uuid.uuid4().hex[:8],
            source='remote', remote_base_url=REMOTE['server_url']))
        other = api('/scans', dict(name='Повтор агента · smoke', type='deep_team', asset_kind='agent',
            asset_id=agent['id'], session_id=str(uuid.uuid4()), config={}))
        other = api(f"/scans/{other['id']}/start", {})
        assert other['status'] == 'failed'
        other_retry = retry(other)
        assert other_retry['status'] == 'failed' and other_retry['agent_config_id'] == agent['id']
        rejected(other, {'mode': 'failed'}, 409)
        rejected(other, {'mode': 'engine', 'engine_id': 'cisco_yara'}, 422)
        passed('non-mcp-full-retry-before-llm', scan_id=other_retry['id'])
    finally:
        start("scanner-mcp-cisco-readiness")
        start("scanner-mcp")
    report = dict(all_passed=True, results=reports)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
