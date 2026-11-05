import hashlib
import io
import ipaddress
import json
import socket
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlmodel import Session, select

from app.auth.deps import accessible_org_ids, ensure_org_access, get_caller, Caller, require_machine
from app.db import get_session
from app.models import MCPArtifact, OrgRole
from app.schemas import MCPArtifactFromURL, MCPArtifactRead

router = APIRouter(prefix="/mcp-artifacts", tags=["mcp-artifacts"])

MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_ARCHIVE_FILES = 5_000
MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
MAX_REDIRECTS = 3


def _safe_filename(value: str | None) -> str:
    filename = Path(unquote(value or "")).name.strip() or "bundle.mcpb"
    filename = "".join(character for character in filename if ord(character) >= 32 and character not in '\\"')
    filename = filename or "bundle.mcpb"
    return filename if filename.lower().endswith(".mcpb") else f"{filename}.mcpb"


def _validate_archive(content: bytes) -> dict:
    if not content:
        raise HTTPException(status_code=422, detail="MCPB-архив пуст")
    if len(content) > MAX_ARCHIVE_BYTES:
        raise HTTPException(status_code=413, detail="MCPB-архив превышает ограничение 50 МиБ")

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            files = archive.infolist()
            if len(files) > MAX_ARCHIVE_FILES:
                raise HTTPException(status_code=422, detail="В MCPB-архиве слишком много файлов")

            total_size = 0
            for item in files:
                path = PurePosixPath(item.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise HTTPException(status_code=422, detail=f"Небезопасный путь в MCPB-архиве: {item.filename}")
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise HTTPException(status_code=422, detail="Символические ссылки в MCPB-архиве запрещены")
                total_size += item.file_size
                if total_size > MAX_UNCOMPRESSED_BYTES:
                    raise HTTPException(status_code=422, detail="Распакованный MCPB превышает ограничение 250 МиБ")

            try:
                manifest_info = archive.getinfo("manifest.json")
            except KeyError as exc:
                raise HTTPException(status_code=422, detail="В корне MCPB-архива отсутствует manifest.json") from exc
            if manifest_info.file_size > MAX_MANIFEST_BYTES:
                raise HTTPException(status_code=422, detail="manifest.json превышает ограничение 1 МиБ")
            try:
                manifest = json.loads(archive.read(manifest_info))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise HTTPException(status_code=422, detail="manifest.json должен содержать корректный JSON") from exc
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=422, detail="Файл не является корректным MCPB/ZIP-архивом") from exc

    if not isinstance(manifest, dict):
        raise HTTPException(status_code=422, detail="manifest.json должен содержать JSON-объект")
    missing = [field for field in ("manifest_version", "name", "version", "server") if field not in manifest]
    if missing:
        raise HTTPException(status_code=422, detail=f"В manifest.json отсутствуют поля: {', '.join(missing)}")
    if not isinstance(manifest["server"], dict):
        raise HTTPException(status_code=422, detail="Поле server в manifest.json должно быть объектом")
    server = manifest["server"]
    if server.get("type") not in {"python", "node"}:
        raise HTTPException(status_code=422, detail="server.type в manifest.json должен быть python или node -- другие рантаймы деплой пока не поддерживает")
    if not isinstance(server.get("entry_point"), str) or not server["entry_point"]:
        raise HTTPException(status_code=422, detail="В manifest.json отсутствует server.entry_point (путь к точке входа сервера)")
    mcp_config = server.get("mcp_config")
    if not isinstance(mcp_config, dict) or not isinstance(mcp_config.get("command"), str) or not mcp_config.get("command"):
        raise HTTPException(status_code=422, detail="В manifest.json нужен server.mcp_config.command -- команда запуска сервера по stdio")
    return manifest


def _assert_public_https_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="Разрешены только HTTPS URI без встроенных учётных данных")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HTTPException(status_code=422, detail="Не удалось определить адрес хоста MCPB") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise HTTPException(status_code=422, detail="URI MCPB не должен указывать на внутренний или служебный адрес")


def _download(url: str) -> tuple[bytes, str, str]:
    current_url = url
    with httpx.Client(follow_redirects=False, timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        for redirect_number in range(MAX_REDIRECTS + 1):
            _assert_public_https_url(current_url)
            try:
                with client.stream("GET", current_url, headers={"Accept": "application/octet-stream, application/zip"}) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        if redirect_number == MAX_REDIRECTS:
                            raise HTTPException(status_code=422, detail="Превышено число перенаправлений при загрузке MCPB")
                        location = response.headers.get("location")
                        if not location:
                            raise HTTPException(status_code=422, detail="Сервер вернул перенаправление без Location")
                        current_url = urljoin(current_url, location)
                        continue
                    response.raise_for_status()
                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > MAX_ARCHIVE_BYTES:
                        raise HTTPException(status_code=413, detail="MCPB-архив превышает ограничение 50 МиБ")
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > MAX_ARCHIVE_BYTES:
                            raise HTTPException(status_code=413, detail="MCPB-архив превышает ограничение 50 МиБ")
                        chunks.append(chunk)
                    filename = _safe_filename(urlparse(current_url).path)
                    return b"".join(chunks), filename, current_url
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=422, detail=f"Не удалось загрузить MCPB: {exc}") from exc
    raise HTTPException(status_code=422, detail="Не удалось загрузить MCPB")


def _save_artifact(
    session: Session,
    *,
    organization_id: int,
    content: bytes,
    filename: str,
    source_type: str,
    source_url: str | None = None,
    expected_sha256: str | None = None,
) -> MCPArtifact:
    manifest = _validate_archive(content)
    digest = hashlib.sha256(content).hexdigest()
    if expected_sha256 and digest != expected_sha256:
        raise HTTPException(status_code=422, detail=f"SHA-256 не совпадает: получен {digest}")
    artifact = MCPArtifact(
        organization_id=organization_id,
        original_filename=_safe_filename(filename),
        source_type=source_type,
        source_url=source_url,
        sha256=digest,
        size_bytes=len(content),
        manifest=manifest,
        content=content,
    )
    session.add(artifact)
    session.commit()
    session.refresh(artifact)
    return artifact


@router.post("/upload", response_model=MCPArtifactRead)
async def upload_artifact(
    organization_id: int = Form(gt=0),
    file: UploadFile = File(...),
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
) -> MCPArtifact:
    ensure_org_access(caller, session, organization_id, min_role=OrgRole.EDITOR)
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_ARCHIVE_BYTES:
            raise HTTPException(status_code=413, detail="MCPB-архив превышает ограничение 50 МиБ")
        chunks.append(chunk)
    return _save_artifact(
        session,
        organization_id=organization_id,
        content=b"".join(chunks),
        filename=file.filename or "bundle.mcpb",
        source_type="upload",
    )


@router.post("/from-url", response_model=MCPArtifactRead)
def download_artifact(
    payload: MCPArtifactFromURL,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
) -> MCPArtifact:
    ensure_org_access(caller, session, payload.organization_id, min_role=OrgRole.EDITOR)
    content, filename, final_url = _download(str(payload.url))
    return _save_artifact(
        session,
        organization_id=payload.organization_id,
        content=content,
        filename=filename,
        source_type="url",
        source_url=final_url,
        expected_sha256=payload.expected_sha256,
    )


@router.get("", response_model=list[MCPArtifactRead])
def list_artifacts(
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
) -> list[MCPArtifact]:
    query = select(MCPArtifact).order_by(MCPArtifact.created_at.desc())
    org_ids = accessible_org_ids(session, caller)
    if org_ids is not None:
        query = query.where(MCPArtifact.organization_id.in_(org_ids))
    return list(session.exec(query).all())


@router.get("/{artifact_id}", response_model=MCPArtifactRead)
def get_artifact(
    artifact_id: int,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
) -> MCPArtifact:
    artifact = session.get(MCPArtifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="MCPB-артефакт не найден")
    ensure_org_access(caller, session, artifact.organization_id)
    return artifact


@router.get("/{artifact_id}/content", dependencies=[Depends(require_machine)])
def get_artifact_content(artifact_id: int, session: Session = Depends(get_session)) -> Response:
    """Сырые байты MCPB -- только для scanner-mcp (машинный контур)."""
    artifact = session.get(MCPArtifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="MCPB-артефакт не найден")
    return Response(
        content=artifact.content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"bundle.mcpb\"; "
                f"filename*=UTF-8''{quote(_safe_filename(artifact.original_filename))}"
            )
        },
    )
