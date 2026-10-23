"""Live registry check; use a test stand without a Snyk token.

Change worker state externally, then run --state healthy/readiness-down/all-down.
Allows the existing control-api schema cache to expire; leaves its test asset.
"""
import argparse
import json
from pathlib import Path
import time
import uuid

from smoke_mcp import api


def options(path):
    registration = next(r for r in api(path) if r["type"] == "mcp")
    assert registration["available"], "MCP coordinator disappeared from registry"
    field = next(f for f in registration["config_schema"]["fields"] if f["name"] == "scanner_ids")
    assert field["default"] == [], "Default selection changed"
    return {o["value"]: o for o in field["options"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", choices=["healthy", "readiness-down", "all-down"], default="healthy")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    ids = {"mcpradar", "cisco_yara", "cisco_readiness", "cisco_prompt_defense", "mcp_dynamic", "semgrep", "snyk"}
    expected = {i: i != "snyk" and args.state != "all-down" and not (args.state == "readiness-down" and i == "cisco_readiness") for i in ids}
    deadline = time.monotonic() + 45
    started = time.monotonic()
    while True:
        actual = options("/scanners")
        assert set(actual) == ids
        if {k: v["available"] for k, v in actual.items()} == expected:
            break
        assert time.monotonic() < deadline, {k: v["available"] for k, v in actual.items()}
        time.sleep(2)
    for key, item in actual.items():
        if expected[key]:
            assert item["reason"] is None
        else:
            assert item["reason"]
            if key != "snyk" or args.state == "all-down":
                assert item["reason"] == "Контейнер сканера недоступен"
    if args.state != "all-down":
        assert "SNYK_TOKEN" in actual["snyk"]["reason"]
    asset = api("/mcp-assets", {"name": "MCP availability " + uuid.uuid4().hex[:8],
        "config": {"kind": "remote", "server_url": "http://mcp-test-target:8000/mcp"}})
    filtered = options(f"/scanners?asset_kind=mcp&asset_id={asset['id']}")
    assert filtered["semgrep"]["available"] is False
    assert "не применим" in filtered["semgrep"]["description"]
    for key in ids - {"semgrep"}:
        assert filtered[key]["available"] == expected[key]
        assert filtered[key]["reason"] == actual[key]["reason"]
    # Filtering for an asset must not mutate the cached global schema.
    assert options("/scanners") == actual
    report = dict(passed=True, state=args.state, asset_id=asset["id"],
                  elapsed_seconds=round(time.monotonic()-started, 2), options=actual, filtered=filtered)
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: report[k] for k in ("passed", "state", "asset_id", "elapsed_seconds")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
