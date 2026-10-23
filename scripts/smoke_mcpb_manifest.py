"""Live MCPB manifest regression: upload/storage/SAST/dynamic and invalid ZIPs.

Only self-contained fixtures; no installs, cloud calls or dangerous tool calls.
Leaves created artifacts/assets/scans for inspection. MCP_TEST_API sets API URL.
"""
import argparse
import io
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid
import zipfile

from smoke_mcp import BASE, VULNERABLE, api
from smoke_mcp_user_config import SERVER

MANIFEST = dict(manifest_version="0.3", name="manifest-regression", version="1.0.0",
    server=dict(type="python", entry_point="server.py",
                mcp_config=dict(command="python", args=["server.py"])))


def upload(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    boundary = "manifest-" + uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="fixture.mcpb"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n').encode()
    body += buffer.getvalue() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(BASE + "/mcp-artifacts/upload", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    reports = []
    for last in (False, True):
        entries = [("server.py", SERVER), ("checks.py", VULNERABLE), ("assets/info.json", '{}')]
        entries.insert(len(entries) if last else 0, ("manifest.json", json.dumps(MANIFEST)))
        code, artifact = upload(entries)
        assert code == 200 and artifact["manifest"] == MANIFEST, artifact
        asset = api("/mcp-assets", dict(name="Manifest regression " + uuid.uuid4().hex[:8],
            config=dict(kind="bundle", artifact_id=artifact["id"])))
        job = api("/scans", dict(name="MCPB · manifest " + ("last" if last else "first"),
            type="mcp", asset_kind="mcp", asset_id=asset["id"], session_id=str(uuid.uuid4()),
            config=dict(scanner_ids=["semgrep", "mcp_dynamic"], allow_tool_calls=True,
                        probes=[dict(tool="ready", arguments={}, contains="fixture-ready")], timeout_seconds=60)))
        api(f"/scans/{job['id']}/start", {})
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            job = api(f"/scans/{job['id']}")
            if job["status"] not in ("pending", "running"):
                break
            time.sleep(1)
        result = json.loads(job.get("results") or '{}')
        assert job["status"] == "success", (job["id"], result)
        sast, dynamic = result["runs"]
        assert sast["engine"] == "semgrep" and len(sast["findings"]) >= 4 and sast["files_checked"] == 2
        assert dynamic["engine"] == "mcp_dynamic" and dynamic["tools_checked"] == 1
        assert len(dynamic["checks"]) == 3 and all(c["status"] == "passed" for c in dynamic["checks"])
        reports.append(dict(case="manifest-last" if last else "manifest-first", passed=True,
                            scan_id=job["id"], summary=result["summary"]))
    for name, entries, message in [
        ("missing", [("server.py", SERVER)], "отсутствует manifest.json"),
        ("nested", [("nested/manifest.json", json.dumps(MANIFEST))], "отсутствует manifest.json"),
        ("bad-json", [("manifest.json", "{")], "корректный JSON"),
        ("not-object", [("manifest.json", "[]")], "JSON-объект"),
        ("bad-encoding", [("manifest.json", b'\xff')], "корректный JSON"),
        ("too-large", [("manifest.json", " " * (1024*1024+1))], "1 МиБ"),
        ("traversal", [("manifest.json", json.dumps(MANIFEST)), ("../outside.json", "{}")], "Небезопасный путь"),
    ]:
        code, error = upload(entries)
        assert code == 422 and message in error.get("detail", ""), (name, code, error)
        reports.append(dict(case=name, passed=True, http_status=code, error=error["detail"]))
    report = dict(all_passed=True, results=reports)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(output)
    print(output)


if __name__ == "__main__":
    main()
