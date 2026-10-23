"""Exercise the real MCPB extractor in a scanner container, without mocks.

docker compose exec -T scanner-mcp python < scripts/check_mcpb_archive.py
"""
import io
import json
from pathlib import Path
import tempfile
import zipfile

from app.target import extract_bundle_archive


def archive_bytes(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return buffer.getvalue()


manifest = {"name": "fixture", "server": {"type": "python"}}
metadata = ("manifest.json", json.dumps(manifest))
source = ("server.py", "raise RuntimeError('Static extraction must not execute code')")
asset = ("assets/info.json", '{"data": true}')
results = []

for order, entries in (("first", [metadata, source, asset]), ("last", [source, asset, metadata])):
    for code_only in (True, False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            actual = extract_bundle_archive(archive_bytes(entries), root, code_only)
            assert actual == manifest
            expected = {"server.py"} if code_only else {"server.py", "manifest.json", "assets/info.json"}
            assert {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()} == expected
            assert (root / "server.py").read_text() == source[1]
        results.append(dict(case=f"manifest-{order}", code_only=code_only, passed=True))

symlink = zipfile.ZipInfo("link.json")
symlink.create_system = 3
symlink.external_attr = 0o120777 << 16
invalid = [
    ("not-zip", b"not a zip", "ZIP-архивом"),
    ("missing", archive_bytes([source]), "отсутствует manifest.json"),
    ("nested", archive_bytes([source, ("nested/manifest.json", metadata[1])]), "отсутствует manifest.json"),
    ("bad-json", archive_bytes([source, ("manifest.json", "{")]), "корректный JSON"),
    ("bad-encoding", archive_bytes([source, ("manifest.json", b'\xff')]), "корректный JSON"),
    ("array", archive_bytes([source, ("manifest.json", "[]")]), "JSON-объект"),
    ("null", archive_bytes([source, ("manifest.json", "null")]), "JSON-объект"),
    ("manifest-limit", archive_bytes([source, ("manifest.json", " " * (1024*1024+1))]), "1 МиБ"),
    ("traversal", archive_bytes([metadata, source, ("../outside.json", "{}")] ), "Небезопасный путь"),
    ("absolute", archive_bytes([metadata, source, ("/outside.json", "{}")] ), "Небезопасный путь"),
    ("backslash", archive_bytes([metadata, source, ("folder\\info.json", "{}")] ), "Небезопасный путь"),
    ("symlink", archive_bytes([metadata, source, (symlink, "../outside")] ), "Небезопасный путь"),
    ("file-count", archive_bytes([metadata] + [(f"{i}.txt", "") for i in range(5000)]), "лимит распаковки"),
]
# A compressed archive exceeds the expanded-size limit without allocating
# or extracting a 251 MiB file on disk.
buffer = io.BytesIO()
with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    archive.writestr(*metadata)
    with archive.open("large.txt", "w") as entry:
        for _ in range(251):
            entry.write(b"0" * (1024 * 1024))
invalid.append(("expanded-size", buffer.getvalue(), "лимит распаковки"))
invalid.append(("archive-size", b"0" * (50 * 1024 * 1024 + 1), "50 МБ"))

for name, content, message in invalid:
    for code_only in (True, False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "bundle"
            root.mkdir()
            try:
                extract_bundle_archive(content, root, code_only)
                raise AssertionError(f"Accepted {name}")
            except ValueError as exc:
                assert message in str(exc), (name, str(exc))
            assert not list(root.iterdir()), f"Partial extraction before rejection: {name}"
            assert list(Path(tmp).iterdir()) == [root]
        results.append(dict(case=name, code_only=code_only, passed=True))

print(json.dumps(dict(passed=True, cases=len(results), results=results), ensure_ascii=False))
