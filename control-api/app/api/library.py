"""Local Markdown knowledge library.

Reads `.md` files from `LIBRARY_DIR` (a read-only directory mounted into the
container), so adding a new research note is just dropping a file in -- no
rebuild, no DB. Category comes from the top-level subfolder (or a
`category` frontmatter override); title/summary/tags/date come from a YAML
frontmatter block, with sensible fallbacks (first heading, file name, mtime).
"""
import os
from datetime import date as date_type, datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/library", tags=["library"])

LIBRARY_DIR = Path(os.environ.get("LIBRARY_DIR", "/library"))
DEFAULT_CATEGORY = "general"


def _split_frontmatter(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            raw = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1 :]).lstrip("\n")
            try:
                parsed = yaml.safe_load(raw) or {}
            except yaml.YAMLError:
                parsed = {}
            return (parsed if isinstance(parsed, dict) else {}), body
    return {}, text


def _first_heading(body: str) -> Optional[str]:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return None


def _as_tags(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(part).strip() for part in value if str(part).strip()]
    return [str(value)]


def _article_paths() -> list[Path]:
    if not LIBRARY_DIR.is_dir():
        return []
    return sorted(
        path
        for path in LIBRARY_DIR.rglob("*.md")
        if not any(part.startswith(".") for part in path.relative_to(LIBRARY_DIR).parts)
    )


def _read(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"не удалось прочитать {path.name}: {exc}") from exc

    meta, body = _split_frontmatter(text)
    rel = path.relative_to(LIBRARY_DIR).with_suffix("")
    parts = rel.parts
    folder_category = parts[0] if len(parts) > 1 else DEFAULT_CATEGORY
    category = str(meta.get("category") or folder_category)
    title = str(meta.get("title") or _first_heading(body) or path.stem)

    date = meta.get("date")
    if isinstance(date, datetime):
        date = date.date().isoformat()
    elif isinstance(date, date_type):
        date = date.isoformat()
    elif date is not None:
        date = str(date)
    else:
        date = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).date().isoformat()

    return {
        "slug": rel.as_posix(),
        "category": category,
        "title": title,
        "summary": str(meta.get("summary") or meta.get("description") or ""),
        "tags": _as_tags(meta.get("tags")),
        "source": str(meta.get("source") or ""),
        "date": date,
        "content": body,
    }


def _resolve(slug: str) -> Path:
    root = LIBRARY_DIR.resolve()
    candidate = (root / f"{slug}.md").resolve()
    if not candidate.is_file() or root not in candidate.parents:
        raise HTTPException(status_code=404, detail="материал не найден")
    return candidate


@router.get("/articles")
def list_articles() -> list[dict]:
    """Metadata for every article, newest first."""
    articles = [_read(path) for path in _article_paths()]
    for article in articles:
        article.pop("content", None)
    articles.sort(key=lambda a: (a["date"], a["title"]), reverse=True)
    return articles


@router.get("/articles/{slug:path}")
def get_article(slug: str) -> dict:
    return _read(_resolve(slug))
