"""Безопасная распаковка zip (D-21, D-44). Вредоносные архивы -- минимальные
инертные конструкции (пути, флаги, нули), без рабочей нагрузки."""
import io
import stat
import struct
import zipfile

import pytest

from app import archive
from app.archive import ArchiveRejected

from conftest import make_zip, skill_md


def _write(tmp_path, content: bytes):
    path = tmp_path / "a.zip"
    path.write_bytes(content)
    dest = tmp_path / "out"
    dest.mkdir()
    return path, dest


def _raw_zip(entries: list[tuple[zipfile.ZipInfo, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for info, data in entries:
            zf.writestr(info, data)
    return buffer.getvalue()


def _set_encrypted_flag(content: bytes) -> bytes:
    """Ставит бит «зашифровано» в локальном и центральном заголовках."""
    data = bytearray(content)
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        start = 0
        while (pos := data.find(signature, start)) != -1:
            flags = struct.unpack_from("<H", data, pos + offset)[0]
            struct.pack_into("<H", data, pos + offset, flags | 0x1)
            start = pos + 4
    return bytes(data)


def test_extracts_regular_archive(tmp_path):
    content = make_zip(
        {"a/SKILL.md": skill_md("a"), "a/scripts/run.sh": "echo ok\n", "b/SKILL.md": skill_md("b"), "./c.txt": "x"}
    )
    path, dest = _write(tmp_path, content)
    assert archive.extract(path, dest) == 4
    assert (dest / "a" / "scripts" / "run.sh").read_text() == "echo ok\n"
    assert (dest / "c.txt").read_text() == "x"
    mode = stat.S_IMODE((dest / "a" / "scripts" / "run.sh").stat().st_mode)
    assert mode == 0o644, "файлы из архива не должны быть исполняемыми"


def test_directory_entries(tmp_path):
    info = zipfile.ZipInfo("empty/")
    content = _raw_zip([(info, b""), (zipfile.ZipInfo("empty/SKILL.md"), b"x")])
    path, dest = _write(tmp_path, content)
    assert archive.extract(path, dest) == 1
    assert (dest / "empty").is_dir()


@pytest.mark.parametrize(
    "name",
    ["../evil.txt", "a/../../evil.txt", "/etc/evil.txt", "..\\evil.txt", "a\\..\\..\\evil.txt", "C:/evil.txt"],
)
def test_zip_slip_rejected(tmp_path, name):
    content = _raw_zip([(zipfile.ZipInfo("ok/SKILL.md"), b"x"), (zipfile.ZipInfo(name), b"x")])
    path, dest = _write(tmp_path, content)
    with pytest.raises(ArchiveRejected) as exc:
        archive.extract(path, dest)
    assert exc.value.reason == "zip_slip"
    assert not (tmp_path / "evil.txt").exists()
    # Отказ до записи: даже безопасная запись не распакована.
    assert not any(dest.rglob("*"))


def test_symlink_rejected(tmp_path):
    link = zipfile.ZipInfo("skill/link")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    content = _raw_zip([(zipfile.ZipInfo("skill/SKILL.md"), b"x"), (link, b"/etc/passwd")])
    path, dest = _write(tmp_path, content)
    with pytest.raises(ArchiveRejected) as exc:
        archive.extract(path, dest)
    assert exc.value.reason == "symlink"


def test_encrypted_rejected(tmp_path):
    content = _set_encrypted_flag(make_zip({"skill/SKILL.md": skill_md("s")}))
    path, dest = _write(tmp_path, content)
    with pytest.raises(ArchiveRejected) as exc:
        archive.extract(path, dest)
    assert exc.value.reason == "encrypted"


def test_compression_ratio_rejected(tmp_path):
    content = make_zip({"skill/SKILL.md": skill_md("s"), "skill/zeros.bin": b"\0" * (4 * 1024 * 1024)})
    path, dest = _write(tmp_path, content)
    with pytest.raises(ArchiveRejected) as exc:
        archive.extract(path, dest)
    assert exc.value.reason == "limits"
    assert "степень сжатия" in exc.value.detail


def test_small_compressible_file_allowed(tmp_path):
    content = make_zip({"skill/SKILL.md": skill_md("s"), "skill/pad.txt": "a" * 500_000})
    path, dest = _write(tmp_path, content)
    assert archive.extract(path, dest) == 2


def test_too_many_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "MAX_FILES", 3)
    content = make_zip({f"s/{i}.txt": "x" for i in range(4)})
    path, dest = _write(tmp_path, content)
    with pytest.raises(ArchiveRejected, match="записей") as exc:
        archive.extract(path, dest)
    assert exc.value.reason == "limits"


def test_total_size_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "MAX_UNCOMPRESSED_BYTES", 1000)
    content = make_zip({"s/a.txt": "x" * 600, "s/b.txt": "y" * 600})
    path, dest = _write(tmp_path, content)
    with pytest.raises(ArchiveRejected) as exc:
        archive.extract(path, dest)
    assert exc.value.reason == "limits"


@pytest.mark.parametrize("second", ["s/a.txt", "s/A.TXT", "s/./a.txt"])
def test_duplicate_paths_rejected(tmp_path, second):
    content = _raw_zip([(zipfile.ZipInfo("s/a.txt"), b"1"), (zipfile.ZipInfo(second), b"2")])
    path, dest = _write(tmp_path, content)
    with pytest.raises(ArchiveRejected, match="повторяющийся путь"):
        archive.extract(path, dest)


def test_lying_size_header_is_corrupt_not_extracted(tmp_path):
    content = bytearray(make_zip({"s/a.txt": "x" * 5000}))
    pos = content.find(b"PK\x01\x02")  # центральный каталог: uncompressed size по смещению 24
    struct.pack_into("<I", content, pos + 24, 10)
    path, dest = _write(tmp_path, bytes(content))
    with pytest.raises(RuntimeError, match="повреждён"):
        archive.extract(path, dest)


def test_not_a_zip(tmp_path):
    path, dest = _write(tmp_path, b"not a zip at all")
    with pytest.raises(RuntimeError, match="не открывается как ZIP"):
        archive.extract(path, dest)
