"""CRUD активов «Skill» (раздел «Активы», вкладка Skills).

Источник -- git-репозиторий или zip-архив. Архив хранится BLOB-ом в PostgreSQL
по образцу MCPArtifact (валидация проще: manifest.json не требуется). Сканирует
актив `scanner-skills` (тип `agent_skills`): байты zip он забирает через
`GET /skill-assets/{id}/content`, параметры git-клона -- из снимка источника в
`Scan.config.source` (см. `app/api/scans.py`).
"""
import hashlib
import io
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlmodel import Session, select

from app.auth.deps import accessible_org_ids, ensure_org_access, get_caller, Caller, require_machine
from app.db import get_session
from app.models import OrgRole, Scan, SkillAsset, SkillSource
from app.schemas import SkillAssetCreate, SkillAssetRead, SkillAssetUpdate

router = APIRouter(prefix="/skill-assets", tags=["skill-assets"])

MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_FILES = 5_000
MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024


def _safe_filename(value: str | None) -> str:
    filename = Path(unquote(value or "")).name.strip() or "skills.zip"
    filename = "".join(character for character in filename if ord(character) >= 32 and character not in '\\"')
    return filename or "skills.zip"


def _validate_archive(content: bytes) -> None:
    if not content:
        raise HTTPException(status_code=422, detail="Архив пуст")
    if len(content) > MAX_ARCHIVE_BYTES:
        raise HTTPException(status_code=413, detail="Архив превышает ограничение 50 МиБ")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            files = archive.infolist()
            if len(files) > MAX_ARCHIVE_FILES:
                raise HTTPException(status_code=422, detail="В архиве слишком много файлов")
            total_size = 0
            for item in files:
                path = PurePosixPath(item.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise HTTPException(status_code=422, detail=f"Небезопасный путь в архиве: {item.filename}")
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise HTTPException(status_code=422, detail="Символические ссылки в архиве запрещены")
                total_size += item.file_size
                if total_size > MAX_UNCOMPRESSED_BYTES:
                    raise HTTPException(status_code=413, detail="Распакованный архив превышает ограничение 250 МиБ")
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=422, detail="Файл не является корректным ZIP-архивом") from exc


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _require_unique_name(name: str, session: Session, exclude_id: int | None = None) -> None:
    query = select(SkillAsset).where(SkillAsset.name == name)
    existing = session.exec(query).first()
    if existing and existing.id != exclude_id:
        raise HTTPException(status_code=409, detail="Актив с таким именем уже существует")


@router.post("", response_model=SkillAssetRead)
def create_skill_asset(
    payload: SkillAssetCreate,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
):
    ensure_org_access(caller, session, payload.organization_id, min_role=OrgRole.EDITOR)
    _require_unique_name(payload.name.strip(), session)
    asset = SkillAsset(
        name=payload.name.strip(),
        organization_id=payload.organization_id,
        description=payload.description,
        source=SkillSource.REPOSITORY,
        git_repo_url=(payload.git_repo_url or "").strip() or None,
        git_ref=(payload.git_ref or "").strip() or "main",
        git_access_token=payload.git_access_token,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.post("/upload", response_model=SkillAssetRead)
def upload_skill_asset(
    organization_id: int = Form(gt=0),
    name: str = Form(min_length=1),
    description: str = Form(default=""),
    file: UploadFile = File(),
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
):
    ensure_org_access(caller, session, organization_id, min_role=OrgRole.EDITOR)
    _require_unique_name(name.strip(), session)
    content = file.file.read()
    _validate_archive(content)
    asset = SkillAsset(
        name=name.strip(),
        organization_id=organization_id,
        description=description.strip() or None,
        source=SkillSource.ZIP,
        archive_filename=_safe_filename(file.filename),
        archive_sha256=_sha256(content),
        archive=content,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.get("", response_model=list[SkillAssetRead])
def list_skill_assets(
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
):
    query = select(SkillAsset).order_by(SkillAsset.created_at.desc())
    org_ids = accessible_org_ids(session, caller)
    if org_ids is not None:
        query = query.where(SkillAsset.organization_id.in_(org_ids))
    return session.exec(query).all()


@router.get("/{asset_id}", response_model=SkillAssetRead)
def get_skill_asset(
    asset_id: int,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
):
    asset = session.get(SkillAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Skill-актив не найден")
    ensure_org_access(caller, session, asset.organization_id)
    return asset


@router.get("/{asset_id}/content", dependencies=[Depends(require_machine)])
def get_skill_asset_content(asset_id: int, session: Session = Depends(get_session)) -> Response:
    """Байты zip-архива для scanner-skills (по образцу /mcp-artifacts/{id}/content).
    У git-актива архива нет -- 409: такой актив сканер клонирует сам."""
    asset = session.get(SkillAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Skill-актив не найден")
    if asset.source != SkillSource.ZIP:
        raise HTTPException(status_code=409, detail="Источник skill-актива -- git-репозиторий, архива нет")
    if not asset.archive:
        raise HTTPException(status_code=404, detail="У skill-актива нет загруженного архива")
    filename = _safe_filename(asset.archive_filename)
    return Response(
        content=asset.archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=\"skills.zip\"; filename*=UTF-8''{quote(filename)}",
            "X-Archive-SHA256": asset.archive_sha256 or "",
        },
    )


@router.put("/{asset_id}", response_model=SkillAssetRead)
def update_skill_asset(
    asset_id: int,
    payload: SkillAssetUpdate,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
):
    asset = session.get(SkillAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Skill-актив не найден")
    ensure_org_access(caller, session, asset.organization_id, min_role=OrgRole.EDITOR)
    updates = payload.model_dump(exclude_unset=True)
    new_name = (updates.get("name") or "").strip()
    if new_name and new_name != asset.name:
        _require_unique_name(new_name, session, exclude_id=asset.id)
        asset.name = new_name
    for key in ("description", "git_repo_url", "git_ref", "git_access_token"):
        if key in updates:
            value = updates[key]
            setattr(asset, key, value.strip() if isinstance(value, str) and key != "git_access_token" else value)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.delete("/{asset_id}", status_code=204)
def delete_skill_asset(
    asset_id: int,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
):
    asset = session.get(SkillAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Skill-актив не найден")
    ensure_org_access(caller, session, asset.organization_id, min_role=OrgRole.ADMIN)
    scans = session.exec(
        select(Scan).where(Scan.asset_kind == "skill").where(Scan.asset_id == asset_id)
    ).all()
    if scans:
        raise HTTPException(
            status_code=409,
            detail=f"У skill-актива есть сканирования ({len(scans)}): сначала удалите их",
        )
    session.delete(asset)
    session.commit()
