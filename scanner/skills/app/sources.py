"""Этап «Получение исходников» (подзадача 5): zip из control-api или git-клон,
затем поиск скиллов.

Скилл -- папка с файлом `SKILL.md`. Вложенный скилл (папка с `SKILL.md` внутри
другого скилла) отдельно не сканируется: его файлы уже входят во внешний.
Ни одного скилла -- `failed`; больше `max_skills` -- `failed` (D-44, D-45).
Отказ архива по признакам атаки -- `ctx.rejected`, дальше runner сразу
сохраняет результат с вердиктом `block` (D-21).
"""
from pathlib import Path

from app import archive, control_client, manifest_check, repo
from app.context import ScanContext

SKILL_FILE = "SKILL.md"
FRONTMATTER_MAX_BYTES = 64 * 1024
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv"}


def frontmatter_name(skill_md: Path) -> str | None:
    """Поле `name` из YAML-frontmatter SKILL.md или None. Только безопасный
    загрузчик и ограниченный размер: файл недоверенный."""
    data = manifest_check.read_frontmatter(skill_md, max_bytes=FRONTMATTER_MAX_BYTES).data or {}
    name = data.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()[:200]
    return None


def find_skills(root: Path) -> list[dict]:
    """Скиллы под `root`, по пути. Симлинки не обходятся."""
    root = root.resolve()
    found: list[Path] = []

    def walk(directory: Path) -> None:
        if (directory / SKILL_FILE).is_file() and not (directory / SKILL_FILE).is_symlink():
            found.append(directory)
            return  # вложенные скиллы -- часть этого
        for child in sorted(directory.iterdir()):
            if child.is_dir() and not child.is_symlink() and child.name not in SKIP_DIRS:
                walk(child)

    walk(root)
    skills = []
    for directory in found:
        relative = directory.relative_to(root).as_posix()
        skills.append(
            {
                "name": frontmatter_name(directory / SKILL_FILE) or (directory.name if relative != "." else "skill"),
                "path": relative,
                "dir": directory,
            }
        )
    return skills


def _fetch_zip(ctx: ScanContext, dest: Path) -> None:
    source = ctx.source
    archive_path = ctx.workdir / "asset.zip"
    sha256, size = control_client.download_skill_archive(
        int(source["asset_id"]), archive_path, max_bytes=archive.MAX_ARCHIVE_BYTES
    )
    if sha256 != source["archive_sha256"]:
        raise RuntimeError("архив skill-актива не совпадает со снимком при создании скана (sha256) -- создайте сканирование заново")
    ctx.source_meta = {
        "kind": "zip",
        "asset_id": source["asset_id"],
        "filename": source.get("archive_filename"),
        "sha256": sha256,
        "size_bytes": size,
    }
    ctx.log(f"Архив получен: {size} байт, sha256 совпадает", phase="Получение исходников")
    try:
        files = archive.extract(archive_path, dest)
    finally:
        archive_path.unlink(missing_ok=True)
    ctx.log(f"Распаковано файлов: {files}", phase="Получение исходников")


def _fetch_repository(ctx: ScanContext, dest: Path) -> None:
    source = ctx.source
    git_ref = source.get("git_ref") or "main"
    commit = repo.clone(
        source["git_repo_url"],
        git_ref,
        source.get("git_access_token"),
        dest,
        timeout=ctx.deadline.remaining(),
    )
    files, size = repo.measure(dest)
    if files > archive.MAX_FILES or size > archive.MAX_UNCOMPRESSED_BYTES:
        raise RuntimeError(
            f"репозиторий слишком большой ({files} файлов, {size // (1024 * 1024)} МиБ; допустимо "
            f"{archive.MAX_FILES} файлов и {archive.MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} МиБ) -- сузьте актив"
        )
    ctx.source_meta = {"kind": "repository", "git_repo_url": source["git_repo_url"], "git_ref": git_ref, "commit": commit}
    ctx.log(f"Склонирован коммит {commit[:12]}: {files} файлов", phase="Получение исходников")


def fetch(ctx: ScanContext) -> None:
    dest = ctx.workdir / "src"
    dest.mkdir()
    try:
        if ctx.source["kind"] == "zip":
            _fetch_zip(ctx, dest)
        else:
            _fetch_repository(ctx, dest)
    except archive.ArchiveRejected as rejected:
        ctx.rejected = {"reason": rejected.reason, "detail": rejected.detail}
        ctx.log(f"Архив отклонён: {rejected.detail}", level="error", phase="Получение исходников")
        return
    ctx.deadline.check()

    skills = find_skills(dest)
    if not skills:
        raise RuntimeError("в источнике не найдено ни одного SKILL.md -- проверьте содержимое актива")
    if len(skills) > ctx.max_skills:
        raise RuntimeError(f"слишком много скиллов: {len(skills)}, допустимо не больше {ctx.max_skills} -- сузьте актив")
    ctx.skills = skills
    shown = ", ".join(f"{s['name']} ({s['path']})" for s in skills[:10])
    more = f" и ещё {len(skills) - 10}" if len(skills) > 10 else ""
    ctx.log(f"Найдено скиллов: {len(skills)}: {shown}{more}", level="success", phase="Получение исходников")
