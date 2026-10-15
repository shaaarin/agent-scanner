"""Безопасная распаковка zip skill-актива (D-21, D-44).

control-api при загрузке уже отсёк `..`, абсолютные пути, симлинки и лимиты
по оглавлению (код лида, не трогаем). Здесь -- вторая линия: каждая запись
проверяется ДО записи на диск, а размер считается по реально прочитанным
байтам, а не по заголовку. Дополнительно к проверкам control-api: сжатие
записи ≤ 100:1, зашифрованные записи, повторяющиеся пути.

Признак атаки -- `ArchiveRejected(reason, detail)`: скан завершается
`completed` с вердиктом `block` и `results.rejected` (§2.7). Битый zip --
обычная ошибка (`failed`).
"""
import stat
import zipfile
from pathlib import Path, PurePosixPath

MAX_ARCHIVE_BYTES = 50 * 1024 * 1024  # как в control-api (skill_assets.py)
MAX_FILES = 5_000
MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
MAX_RATIO = 100  # D-44
RATIO_MIN_BYTES = 1024 * 1024  # маленькие файлы с сильным сжатием (нули, повторы) -- норма
_CHUNK = 64 * 1024


class ArchiveRejected(Exception):
    """Архив отклонён по признакам атаки; reason -- zip_slip|symlink|encrypted|limits."""

    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def _safe_relative(name: str) -> PurePosixPath:
    """Путь записи внутри архива или ArchiveRejected(zip_slip)."""
    if "\x00" in name:
        raise ArchiveRejected("zip_slip", f"нулевой байт в пути записи: {name!r}")
    # Обратный слеш в zip -- признак архива из Windows или попытка обойти
    # проверку пути; считаем его разделителем и проверяем как обычно.
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        raise ArchiveRejected("zip_slip", f"абсолютный путь в архиве: {name}")
    parts = [part for part in path.parts if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ArchiveRejected("zip_slip", f"путь выходит за пределы архива: {name}")
    return PurePosixPath(*parts) if parts else PurePosixPath(".")


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def _check_entries(infos: list[zipfile.ZipInfo]) -> None:
    if len(infos) > MAX_FILES:
        raise ArchiveRejected("limits", f"в архиве {len(infos)} записей, допустимо не больше {MAX_FILES}")
    declared = 0
    seen: set[str] = set()
    for info in infos:
        relative = _safe_relative(info.filename)
        if _is_symlink(info):
            raise ArchiveRejected("symlink", f"символическая ссылка в архиве: {info.filename}")
        if info.flag_bits & 0x1:
            raise ArchiveRejected("encrypted", f"зашифрованная запись: {info.filename}")
        key = str(relative).lower()
        if key in seen and not info.is_dir():
            raise ArchiveRejected("zip_slip", f"повторяющийся путь в архиве: {info.filename}")
        seen.add(key)
        declared += info.file_size
        if declared > MAX_UNCOMPRESSED_BYTES:
            raise ArchiveRejected("limits", f"распакованный архив больше {MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} МиБ")
        if info.file_size > RATIO_MIN_BYTES:
            ratio = info.file_size / max(info.compress_size, 1)
            if ratio > MAX_RATIO:
                raise ArchiveRejected(
                    "limits", f"степень сжатия {info.filename} — {ratio:.0f}:1, допустимо не больше {MAX_RATIO}:1"
                )


def extract(archive_path: Path, dest: Path) -> int:
    """Распаковывает архив в `dest` (должна существовать и быть пустой).
    Возвращает число записанных файлов."""
    dest = dest.resolve()
    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as exc:
        raise RuntimeError("архив skill-актива повреждён: не открывается как ZIP") from exc
    written_total = 0
    files = 0
    with archive:
        infos = archive.infolist()
        _check_entries(infos)
        for info in infos:
            relative = _safe_relative(info.filename)
            target = (dest / relative).resolve()
            # Дублирующая проверка на итоговом пути: ни одна запись не
            # пишется вне dest, даже если проверка имени что-то упустила.
            if target != dest and dest not in target.parents:
                raise ArchiveRejected("zip_slip", f"путь выходит за пределы архива: {info.filename}")
            if info.is_dir() or str(relative) == ".":
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                raise ArchiveRejected("zip_slip", f"повторяющийся путь в архиве: {info.filename}")
            written = 0
            try:
                with archive.open(info) as src, target.open("wb") as out:
                    while chunk := src.read(_CHUNK):
                        written += len(chunk)
                        written_total += len(chunk)
                        # Реально прочитанные байты, а не заголовок: заголовок
                        # может врать о размере.
                        if written > info.file_size or written_total > MAX_UNCOMPRESSED_BYTES:
                            raise ArchiveRejected("limits", f"размер {info.filename} больше заявленного в заголовке")
                        out.write(chunk)
            except (zipfile.BadZipFile, EOFError, OSError) as exc:
                raise RuntimeError(f"архив skill-актива повреждён: {info.filename}: {exc}") from exc
            # Ничего из архива не должно быть исполняемым.
            target.chmod(0o644)
            files += 1
    return files
