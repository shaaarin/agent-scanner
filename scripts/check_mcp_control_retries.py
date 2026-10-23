"""Check MCP control-client HTTP retry policy with a local fault server.

Run in the scanner-mcp container: python < scripts/check_mcp_control_retries.py
Uses real loopback HTTP, no LLM/engine mocks and no test framework.
"""
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

import httpx
from app import control_client as control

counts = Counter()
bodies = {}


class Handler(BaseHTTPRequestHandler):
    def do_PATCH(self):
        counts[self.path] += 1
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        bodies.setdefault(self.path, []).append(body)
        code = int(self.path.strip("/").split("/")[0])
        status = code if counts[self.path] == 1 or code in (404, 422) else 200
        if code == 408:  # HTTP 408 isn't in the chosen retry policy
            status = 408
        if code == 200 and counts[self.path] == 1:
            time.sleep(6)  # first response exceeds the client's 5s read timeout
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            self.wfile.write(b'{}')
        except BrokenPipeError:
            pass

    do_POST = do_PATCH

    def log_message(self, *_):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
old_client = control._client
try:
    control._client = httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}")
    for status in (429, 500, 502, 503, 504):
        path = f"/{status}"
        control._request("PATCH", path, json={"results": "unchanged-checkpoint"})
        assert counts[path] == 2
        assert bodies[path][0] == bodies[path][1], "Retry changed the checkpoint"
    for status in (404, 408, 422):
        path = f"/{status}"
        try:
            control._request("PATCH", path, json={})
            raise AssertionError("Permanent HTTP error ignored")
        except httpx.HTTPStatusError as exc:
            assert exc.response.status_code == status and counts[path] == 1
    control._request("PATCH", "/200", json={})
    assert counts["/200"] == 2, "Read timeout wasn't retried"
    # post_log must notice non-2xx responses and remain nonfatal to the scan.
    class LogHandler(Handler):
        def do_POST(self):
            counts[self.path] += 1
            self.send_response(422)
            self.end_headers()
    server.RequestHandlerClass = LogHandler
    assert control.post_log(1, "fixture") is False
    assert counts["/scans/1/logs"] == 1
    print(json.dumps(dict(passed=True, cases=10, request_counts=dict(counts))))
finally:
    control._client.close()
    control._client = old_client
    old_client.close()
    server.shutdown()
    server.server_close()
    thread.join()
