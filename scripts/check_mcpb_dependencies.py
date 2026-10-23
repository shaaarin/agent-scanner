"""Real offline pip installs and MCP sessions; run inside an MCP worker.

Builds harmless wheel fixtures locally. No downloads or external packages.
"""
import asyncio
import io
import json
import os
from pathlib import Path
import tempfile
import zipfile


PACKAGE = "mcpb_fixture_dependency"
WHEEL = PACKAGE + "-1.0.0-py3-none-any.whl"
MANIFEST = {"manifest_version": "0.3", "name": "python-deps-fixture", "version": "1.0.0",
            "server": {"type": "python", "entry_point": "server.py", "mcp_config": {
                "command": "python", "args": ["${__dirname}/server.py"],
                "env": {"PYTHONPATH": "${__dirname}/vendor"}}}}
SERVER = '''import os
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from mcpb_fixture_dependency import marker
from manifest_library import manifest_marker
root = Path(__file__).resolve().parent
paths = os.environ["PYTHONPATH"].split(os.pathsep)
assert paths == [str(root / ".bundle-deps"), str(root / "vendor")]
assert manifest_marker == "manifest-path-preserved"
mcp = FastMCP("python-deps-fixture")
@mcp.tool()
def ready() -> str:
    """Return a harmless marker supplied by this bundle's own dependency."""
    return marker
if __name__ == "__main__":
    mcp.run(transport="stdio")
'''


def fixture(marker):
    wheel_data = io.BytesIO()
    info = PACKAGE + "-1.0.0.dist-info/"
    with zipfile.ZipFile(wheel_data, "w") as wheel:
        wheel.writestr(PACKAGE + "/__init__.py", "marker = " + repr(marker) + "\n")
        wheel.writestr(info + "METADATA", "Metadata-Version: 2.1\nName: mcpb-fixture-dependency\nVersion: 1.0.0\n")
        wheel.writestr(info + "WHEEL", "Wheel-Version: 1.0\nGenerator: local-fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        wheel.writestr(info + "RECORD", "")
    return [("manifest.json", json.dumps(MANIFEST)), ("server.py", SERVER),
            ("requirements.txt", "--no-index\n./" + WHEEL + "\n"),
            (WHEEL, wheel_data.getvalue()),
            ("vendor/manifest_library.py", 'manifest_marker = "manifest-path-preserved"\n')]


async def main():
    import importlib.util
    from app.target import stdio_session_for_bundle, deploy_and_check
    assert importlib.util.find_spec(PACKAGE) is None, "Fixture must not be installed in the image"
    before = dict(os.environ)
    with tempfile.TemporaryDirectory(prefix="mcpb-deps-check-") as tmp:
        async def check(marker):
            root = Path(tmp) / marker
            root.mkdir()
            for name, data in fixture(marker):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data if isinstance(data, bytes) else data.encode())
            async with stdio_session_for_bundle(root, MANIFEST, {}) as session:
                assert len((await session.list_tools()).tools) == 1
                result = await session.call_tool("ready", {})
                assert not result.isError and result.content[0].text == marker
                assert (root / ".bundle-deps" / PACKAGE / "__init__.py").is_file()
            assert dict(os.environ) == before
        await asyncio.gather(check("bundle-A"), check("bundle-B"))
        plain = Path(tmp) / "plain"
        plain.mkdir()
        assert await deploy_and_check(plain, MANIFEST) is None
        (plain / "requirements.txt").write_text("--no-index\n./missing.whl\n")
        try:
            await deploy_and_check(plain, MANIFEST)
        except ValueError as exc:
            assert "pip install" in str(exc)
        else:
            raise AssertionError("Invalid requirement must fail")
        assert dict(os.environ) == before
        assert importlib.util.find_spec(PACKAGE) is None
    print("MCPB dependencies: real offline installs, two isolated MCP processes, "
          "manifest PYTHONPATH preserved, global env unchanged, missing requirements "
          "and install failure OK")


if __name__ == "__main__":
    asyncio.run(main())
