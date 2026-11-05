import json
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlmodel import Session, delete, or_, select

from app.auth.deps import accessible_org_ids, ensure_org_access, get_caller, Caller, require_machine
from app.db import engine, get_session
from app.models import (
    AgentConfig,
    AgentSource,
    AssetKind,
    InjectionTrial,
    MCPArtifact,
    McpAsset,
    OrgRole,
    Scan,
    ScanLog,
    ScanLogLevel,
    ScanStatus,
    ScanType,
    SkillAsset,
    SkillSource,
    TrafficEvent,
)
from app.schemas import MCPScanConfig, ScanCreate, ScanLogCreate, ScanRetry, ScanUpdate
from app.mcp_config import plan, upgrade_flat
from app.scanner_registry import find

router = APIRouter(prefix="/scans", tags=["scans"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _log(session: Session, scan_id: int, message: str, *, level: ScanLogLevel = ScanLogLevel.INFO, phase: Optional[str] = None) -> None:
    session.add(ScanLog(scan_id=scan_id, level=level, phase=phase, message=message))


def _compose_mcp_config(asset_target: dict, scanner_params: dict) -> str:
    """Собирает Scan.config для MCP-скана: цель -- из актива, параметры
    проверок -- из запроса (scanner_ids, timeout_seconds, probes, ...).
    Неизвестные ключи отсеивает схема MCPScanConfig, так что контракт
    scanner-mcp не меняется, а конфиг нормализуется заранее."""
    if "target" in scanner_params:
        raise HTTPException(
            status_code=422,
            detail="Цель MCP-скана берётся из актива: параметр config.target передавать нельзя",
        )
    try:
        config = MCPScanConfig.model_validate({**scanner_params, "target": asset_target})
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc
    return json.dumps(config.model_dump(mode="json"), ensure_ascii=False)


def _report(scan: Scan) -> dict:
    try:
        result = json.loads(scan.results or "{}")
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError):
        return {}


def _retry_status(scan: Scan) -> ScanStatus:
    # Historical MCP reports used completed/completed_with_errors.
    if scan.type == ScanType.MCP and scan.status == ScanStatus.COMPLETED:
        result = _report(scan)
        summary = result.get("summary")
        if isinstance(summary, dict) and isinstance(summary.get("completed"), (int, float)) and isinstance(summary.get("failed"), (int, float)):
            if not summary["completed"]:
                return ScanStatus.FAILED
            return ScanStatus.PARTIALLY_FAILED if summary["failed"] or summary.get("pending") else ScanStatus.SUCCESS
        if result.get("status") == "failed":
            return ScanStatus.FAILED
        if result.get("status") in {"partially_failed", "completed_with_errors"}:
            return ScanStatus.PARTIALLY_FAILED
    return scan.status


def _attempts(session: Session, scan: Scan) -> list[Scan]:
    root_id = scan.retry_root_scan_id or scan.id
    return session.exec(select(Scan).where(or_(
        Scan.id == root_id, Scan.retry_root_scan_id == root_id,
    )).order_by(Scan.created_at, Scan.id)).all()


def _retry_engines(scan: Scan) -> list[dict]:
    if scan.type != ScanType.MCP:
        return []
    try:
        tasks = plan(json.loads(scan.config))
    except (ValueError, KeyError, TypeError, AttributeError):
        return []
    report = _report(scan)
    runs = report.get("runs", [report])
    outcomes = {r["engine"]: r for r in runs if isinstance(r, dict) and isinstance(r.get("engine"), str)} if isinstance(runs, list) else {}
    engines = []
    for engine_id in dict.fromkeys(t["engine"] for t in tasks):
        outcome = outcomes.get(engine_id, {})
        status = outcome.get("status")
        # Older successful engine reports didn't always include a status.
        if status in {"completed", "success"} or (outcome and status is None and not outcome.get("error")):
            status = "success"
        elif status == "failed" or outcome.get("error"):
            status = "failed"
        else:
            status = "pending"
        engines.append(dict(id=engine_id, name=outcome.get("engine_name") or engine_id, status=status))
    return engines


def _retry_options(session: Session, scan: Scan) -> dict:
    attempts = _attempts(session, scan)
    active = next((s for s in attempts if s.status in {ScanStatus.PENDING, ScanStatus.RUNNING}), None)
    status = _retry_status(scan)
    terminal = status in {ScanStatus.COMPLETED, ScanStatus.SUCCESS, ScanStatus.PARTIALLY_FAILED, ScanStatus.FAILED}
    engines = _retry_engines(scan)
    can_all = status in {ScanStatus.FAILED, ScanStatus.PARTIALLY_FAILED}
    return dict(
        can_retry_all=can_all and active is None,
        can_retry_failed=can_all and active is None and any(e["status"] != "success" for e in engines),
        engines=engines if terminal and active is None else [],
        active_scan_id=active.id if active else None,
        attempts=[dict(id=s.id, retry_of_scan_id=s.retry_of_scan_id, retry_mode=s.retry_mode,
                       status=_retry_status(s), created_at=s.created_at,
                       started_at=s.started_at, finished_at=s.finished_at) for s in attempts],
    )


def _compose_skill_config(asset: SkillAsset, scanner_params: dict) -> str:
    """Собирает Scan.config для скана skills: параметры формы (движки и т.п.)
    плюс снимок источника актива в `source` -- как цель MCP в `target`, чтобы
    правка актива не переписывала уже созданный скан. Для git в снимок
    попадает и токен (принятый техдолг MVP, как у MCP repository); байты zip
    не копируются -- сканер берёт их из GET /skill-assets/{id}/content и
    сверяет с `archive_sha256`."""
    if asset.source == SkillSource.ZIP:
        if not asset.archive:
            raise HTTPException(status_code=422, detail="У skill-актива нет загруженного архива")
        source = {
            "kind": SkillSource.ZIP.value,
            "asset_id": asset.id,
            "archive_filename": asset.archive_filename,
            "archive_sha256": asset.archive_sha256,
        }
    else:
        if not (asset.git_repo_url or "").strip():
            raise HTTPException(status_code=422, detail="У skill-актива не задан git-репозиторий")
        source = {
            "kind": SkillSource.REPOSITORY.value,
            "git_repo_url": asset.git_repo_url,
            "git_ref": asset.git_ref or "main",
            "git_access_token": asset.git_access_token,
        }
    # Источник задаёт только актив: одноимённый ключ из запроса перекрывается.
    return json.dumps({**scanner_params, "source": source}, ensure_ascii=False)


@router.get("")
def list_scans(
    agent_config_id: Optional[int] = Query(None),
    asset_kind: Optional[AssetKind] = Query(None),
    asset_id: Optional[int] = Query(None),
    scan_type: Optional[ScanType] = Query(None),
    status: Optional[ScanStatus] = Query(None),
    caller: Caller = Depends(get_caller),
) -> list[Scan]:
    """List all scans with optional filters. Обычный пользователь видит сканы
    своих организаций; машинный контур и системный админ -- все."""
    with Session(engine) as session:
        statement = select(Scan)
        if agent_config_id is not None:
            statement = statement.where(Scan.agent_config_id == agent_config_id)
        if asset_kind is not None:
            statement = statement.where(Scan.asset_kind == asset_kind)
        if asset_id is not None:
            statement = statement.where(Scan.asset_id == asset_id)
        if scan_type is not None:
            statement = statement.where(Scan.type == scan_type)
        if status is not None:
            statement = statement.where(Scan.status == status)
        org_ids = accessible_org_ids(session, caller)
        if org_ids is not None:
            statement = statement.where(Scan.organization_id.in_(org_ids))
        statement = statement.order_by(Scan.created_at.desc())
        return session.exec(statement).all()


@router.get("/active", dependencies=[Depends(require_machine)])
def get_active_scan(session_id: str = Query(...)) -> Optional[dict]:
    """Get active scan for a session (for proxy to know which scan to log events for)."""
    with Session(engine) as session:
        statement = (
            select(Scan)
            .where(Scan.session_id == session_id)
            .where(Scan.status == ScanStatus.RUNNING)
            .order_by(Scan.started_at.desc())
            .limit(1)
        )
        scan = session.exec(statement).first()
        if not scan:
            return None
        return {
            "scan_id": scan.id,
            "name": scan.name,
            "type": scan.type,
            "agent_config_id": scan.agent_config_id,
            "status": scan.status,
            "config": scan.config,
        }


@router.get("/{scan_id}/agent-config", dependencies=[Depends(require_machine)])
def get_scan_agent_config(scan_id: int) -> dict:
    """Get agent config for a scan (for DeepTeam to know which agent it's testing).
    Внутри env-переменные агента -- только сервисам платформы."""
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")

        if scan.agent_config_id is None:
            raise HTTPException(status_code=404, detail="У этого MCP-скана нет конфигурации агента")
        agent_config = session.get(AgentConfig, scan.agent_config_id)
        if not agent_config:
            raise HTTPException(status_code=404, detail="Agent config not found")

        return {
            "id": agent_config.id,
            "name": agent_config.name,
            "source": agent_config.source,
            "git_repo_url": agent_config.git_repo_url,
            "git_ref": agent_config.git_ref,
            "dockerfile_path": agent_config.dockerfile_path,
            "api_port": agent_config.api_port,
            "remote_base_url": agent_config.remote_base_url,
            "remote_headers": agent_config.remote_headers or {},
            "interaction_mode": agent_config.interaction_mode,
            "api_config": agent_config.api_config,
            "langgraph_config": agent_config.langgraph_config,
            "env_vars": {k: v for k, v in agent_config.env_vars.items() if k.startswith("OPENAI_") or k.startswith("ANTHROPIC_")},
        }


@router.post("")
def create_scan(
    payload: ScanCreate,
    caller: Caller = Depends(get_caller),
) -> Scan:
    """Создать скан внутри актива (раздел «Активы»). Применимость сканера к
    виду актива и валидность конфига определяются реестром сканеров.
    Организация скана -- организация актива."""
    registration = find(payload.type)
    if registration is None:
        raise HTTPException(status_code=400, detail=f"Для типа сканирования {payload.type} сканер пока не подключён")
    if payload.asset_kind not in registration.asset_kinds:
        raise HTTPException(
            status_code=422,
            detail=f"Сканер «{registration.name}» не работает с активами типа «{payload.asset_kind.value}»",
        )

    with Session(engine) as session:
        asset_model = {
            AssetKind.AGENT: AgentConfig,
            AssetKind.MCP: McpAsset,
            AssetKind.SKILL: SkillAsset,
        }[payload.asset_kind]
        asset = session.get(asset_model, payload.asset_id)
        if asset is None:
            raise HTTPException(status_code=422, detail=f"Актив («{payload.asset_kind}», id={payload.asset_id}) не найден")
        ensure_org_access(caller, session, asset.organization_id, min_role=OrgRole.EDITOR)

        # Remote-агент не собирается платформой и его трафик к LLM не проходит
        # через наш прокси: анализ кода без репозитория, а инъекциям некуда
        # подкладываться. Осмысленно только атака по его HTTP API
        # (динамическое тестирование и PyRIT).
        _remote_interactive = (ScanType.DEEP_TEAM, ScanType.PYRIT_SCAN)
        if (
            payload.asset_kind == AssetKind.AGENT
            and getattr(asset, "source", None) == AgentSource.REMOTE
            and payload.type not in _remote_interactive
        ):
            raise HTTPException(
                status_code=422,
                detail="Для удалённого агента доступны только динамическое тестирование и PyRIT: "
                "анализу кода нужен репозиторий, а инъекциям — трафик агента через прокси платформы",
            )

        config_json = "{}"
        if payload.asset_kind == AssetKind.MCP:
            config_json = _compose_mcp_config(asset.config, payload.config)
        elif payload.asset_kind == AssetKind.SKILL:
            config_json = _compose_skill_config(asset, payload.config or {})
        elif payload.asset_kind == AssetKind.AGENT:
            # Параметры сканера из динамической формы (поля его /schema).
            config_json = json.dumps(payload.config or {}, ensure_ascii=False)

        scan = Scan(
            name=payload.name.strip(),
            type=payload.type,
            organization_id=asset.organization_id,
            asset_kind=payload.asset_kind,
            asset_id=payload.asset_id,
            # Сканеры и launcher читают только agent_config_id.
            agent_config_id=payload.asset_id if payload.asset_kind == AssetKind.AGENT else None,
            status=ScanStatus.PENDING,
            session_id=payload.session_id,
            config=config_json,
        )
        if config_json != "{}" and registration.validate_config is not None:
            registration.validate_config(config_json)
        session.add(scan)
        session.commit()
        session.refresh(scan)
        return scan


@router.get("/{scan_id}")
def get_scan(
    scan_id: int,
    caller: Caller = Depends(get_caller),
) -> Scan:
    """Get a scan by ID."""
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        ensure_org_access(caller, session, scan.organization_id)
        return scan


@router.patch("/{scan_id}", dependencies=[Depends(require_machine)])
def update_scan(scan_id: int, payload: ScanUpdate) -> Scan:
    """Update scan status/progress/launch metadata (used by scanner/launcher)."""
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(scan, key, value)
        session.add(scan)
        session.commit()
        session.refresh(scan)
        return scan


@router.delete("/{scan_id}")
def delete_scan(
    scan_id: int,
    caller: Caller = Depends(get_caller),
) -> dict:
    """Delete a scan and its progress log. Удаление -- для администратора
    организации (история проверок -- не только «своё»)."""
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        ensure_org_access(caller, session, scan.organization_id, min_role=OrgRole.ADMIN)

        # Use the same family lock as retry creation so a parent cannot be
        # removed while another request is attaching a new attempt to it.
        if session.exec(select(Scan).where(Scan.id == (scan.retry_root_scan_id or scan.id)).with_for_update()).first() is None:
            raise HTTPException(status_code=404, detail="Scan not found")
        scan = session.exec(select(Scan).where(Scan.id == scan_id).with_for_update().execution_options(populate_existing=True)).first()
        if scan is None:
            raise HTTPException(status_code=404, detail="Scan not found")
        if scan.status == ScanStatus.RUNNING:
            raise HTTPException(status_code=409, detail="Нельзя удалить выполняющийся скан")
        if session.exec(select(Scan.id).where(Scan.retry_of_scan_id == scan_id).limit(1)).first() is not None:
            raise HTTPException(status_code=409, detail="У скана есть повторные попытки. Сначала удалите их, чтобы сохранить связи истории")
        session.exec(delete(ScanLog).where(ScanLog.scan_id == scan_id))
        session.exec(delete(InjectionTrial).where(InjectionTrial.scan_id == scan_id))
        # Перехваченный трафик скана тоже удаляем: иначе осиротевшие события с
        # переиспользованными scan_id/trial_id «подмешиваются» к новому
        # скану (особенно критично для косвенных инъекций, где трафик
        # группируется по trial_id).
        session.exec(delete(TrafficEvent).where(TrafficEvent.scan_id == scan_id))
        session.delete(scan)
        session.commit()
        return {"message": "Scan deleted"}


@router.post("/{scan_id}/start")
def start_scan(
    scan_id: int,
    caller: Caller = Depends(get_caller),
) -> Scan:
    """Mark a scan RUNNING and hand it off to the scanner service for its type
    (see scanner_registry). The scanner works in the background; the logs it
    writes are what the scan detail page polls."""
    with Session(engine) as session:
        scan = session.exec(select(Scan).where(Scan.id == scan_id).with_for_update()).first()
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        ensure_org_access(caller, session, scan.organization_id, min_role=OrgRole.EDITOR)
        if scan.status != ScanStatus.PENDING:
            raise HTTPException(status_code=400, detail="Scan can only be started from PENDING status")
        registration = find(scan.type)
        if registration is None:
            raise HTTPException(status_code=400, detail=f"Для типа сканирования {scan.type.value} сканер пока не подключён")
        if registration.validate_config is not None:
            registration.validate_config(scan.config)

        # Fresh progress log for this run.
        session.exec(delete(ScanLog).where(ScanLog.scan_id == scan_id))
        scan.status = ScanStatus.RUNNING
        scan.phase = "Запуск"
        scan.error = None
        scan.results = None
        scan.started_at = utcnow()
        scan.finished_at = None
        message = "Сканирование поставлено в очередь"
        if scan.retry_of_scan_id is not None:
            message += f". Повторная попытка скана №{scan.retry_of_scan_id}"
        _log(session, scan_id, message, phase="Запуск")
        session.add(scan)
        session.commit()
        session.refresh(scan)

    try:
        with httpx.Client(timeout=15.0) as client:
            client.post(f"{registration.url}/run/{scan_id}").raise_for_status()
    except httpx.HTTPError as exc:
        with Session(engine) as session:
            scan = session.get(Scan, scan_id)
            scan.status = ScanStatus.FAILED
            scan.phase = "Ошибка"
            scan.error = f"{registration.service} недоступен: {exc}"
            scan.finished_at = utcnow()
            _log(session, scan_id, f"Не удалось запустить {registration.service}: {exc}", level=ScanLogLevel.ERROR, phase="Ошибка")
            session.add(scan)
            session.commit()
            session.refresh(scan)
        return scan

    return scan


@router.get("/{scan_id}/retries")
def scan_retries(
    scan_id: int,
    caller: Caller = Depends(get_caller),
) -> dict:
    """Available retry actions and lightweight history; no reports duplicated."""
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        ensure_org_access(caller, session, scan.organization_id)
        return _retry_options(session, scan)


@router.post("/{scan_id}/retry")
def retry_scan(
    scan_id: int,
    payload: ScanRetry,
    caller: Caller = Depends(get_caller),
) -> Scan:
    """Create and start a separate attempt using the saved scan configuration."""
    with Session(engine) as session:
        source = session.get(Scan, scan_id)
        if not source:
            raise HTTPException(status_code=404, detail="Scan not found")
        ensure_org_access(caller, session, source.organization_id, min_role=OrgRole.EDITOR)
        root_id = source.retry_root_scan_id or source.id
        # Serialize requests across the whole attempt family, including
        # retries requested simultaneously from different history pages.
        if session.exec(select(Scan).where(Scan.id == root_id).with_for_update()).first() is None:
            raise HTTPException(status_code=404, detail="Scan not found")
        source = session.exec(select(Scan).where(Scan.id == scan_id).with_for_update().execution_options(populate_existing=True)).first()
        if source is None:
            raise HTTPException(status_code=404, detail="Scan not found")
        options = _retry_options(session, source)
        if options["active_scan_id"] is not None:
            raise HTTPException(status_code=409, detail=f"В этой истории уже ожидает запуска или выполняется скан №{options['active_scan_id']}")
        if payload.mode == "all" and not options["can_retry_all"]:
            raise HTTPException(status_code=409, detail="Целиком можно повторить только проваленный или частично выполненный скан")
        if payload.mode == "failed" and not options["can_retry_failed"]:
            raise HTTPException(status_code=409, detail="Нет незавершённых MCP-движков для повторного запуска")
        engine_ids = [e["id"] for e in options["engines"]]
        if payload.mode == "engine" and payload.engine_id not in engine_ids:
            raise HTTPException(status_code=422, detail="Движок не входит в исходный план MCP-скана или скан ещё не завершён")

        registration = find(source.type)
        if registration is None:
            raise HTTPException(status_code=400, detail="Для этого типа скана сканер пока не подключён")
        if source.agent_config_id is not None and session.get(AgentConfig, source.agent_config_id) is None:
            raise HTTPException(status_code=422, detail="Конфигурация агента больше не доступна")
        try:
            config = json.loads(source.config)
            if not isinstance(config, dict):
                raise ValueError("ожидается JSON-объект")
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail="Сохранённая конфигурация скана некорректна") from exc
        if payload.mode != "all":
            config = upgrade_flat(config)
            config["scanner_ids"] = ([payload.engine_id] if payload.mode == "engine" else
                                     [e["id"] for e in options["engines"] if e["status"] != "success"])
        config_json = json.dumps(config, ensure_ascii=False)
        if registration.validate_config is not None:
            registration.validate_config(config_json)
        if source.type == ScanType.MCP:
            target = upgrade_flat(config).get("target", {})
            if target.get("kind") == "bundle" and session.get(MCPArtifact, target.get("artifact_id")) is None:
                raise HTTPException(status_code=422, detail="Исходный MCPB-архив больше не доступен")
        attempt = Scan(
            name=source.name, type=source.type, organization_id=source.organization_id,
            asset_kind=source.asset_kind, asset_id=source.asset_id,
            agent_config_id=source.agent_config_id, session_id=str(uuid4()), config=config_json,
            retry_of_scan_id=source.id, retry_root_scan_id=root_id, retry_mode=payload.mode,
        )
        session.add(attempt)
        session.flush()
        session.commit()
        session.refresh(attempt)
        attempt_id = attempt.id
    # The committed pending row blocks concurrent retries before dispatch.
    # Dispatch failures become a separate failed attempt, leaving the source.
    return start_scan(attempt_id, caller)


@router.get("/{scan_id}/logs")
def list_scan_logs(
    scan_id: int,
    after_id: int = Query(default=0),
    limit: int = Query(default=500, le=2000),
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_session),
) -> list[ScanLog]:
    """Incremental progress log: pass the last `id` you've seen as `after_id`."""
    scan = session.get(Scan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    ensure_org_access(caller, session, scan.organization_id)
    statement = (
        select(ScanLog)
        .where(ScanLog.scan_id == scan_id)
        .where(ScanLog.id > after_id)
        .order_by(ScanLog.id)
        .limit(limit)
    )
    return session.exec(statement).all()


@router.post("/{scan_id}/logs", dependencies=[Depends(require_machine)])
def create_scan_log(
    scan_id: int,
    payload: ScanLogCreate,
    session: Session = Depends(get_session),
) -> ScanLog:
    """Append one progress line (called by the scanner)."""
    scan = session.get(Scan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    log = ScanLog(scan_id=scan_id, **payload.model_dump())
    session.add(log)
    session.commit()
    session.refresh(log)
    return log


@router.post("/{scan_id}/complete", dependencies=[Depends(require_machine)])
def complete_scan(scan_id: int, results: str) -> Scan:
    """Mark a scan as completed with results."""
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        if scan.status != ScanStatus.RUNNING:
            raise HTTPException(status_code=400, detail="Scan can only be completed from RUNNING status")

        scan.status = ScanStatus.COMPLETED
        scan.phase = "Завершено"
        scan.results = results
        scan.finished_at = utcnow()
        session.add(scan)
        session.commit()
        session.refresh(scan)
        return scan


@router.post("/{scan_id}/fail", dependencies=[Depends(require_machine)])
def fail_scan(scan_id: int, error: str) -> Scan:
    """Mark a scan as failed."""
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")

        scan.status = ScanStatus.FAILED
        scan.phase = "Ошибка"
        scan.error = error
        scan.results = json.dumps({"error": error})
        scan.finished_at = utcnow()
        session.add(scan)
        session.commit()
        session.refresh(scan)
        return scan
