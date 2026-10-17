"""Отчёты, сводка по активу и выгрузки результатов.

- `GET /scans/{id}/report` -- единый отчёт скана (`app/reports.py`): одинаковые
  метрики и одинаковый формат находок независимо от сканера.
- `GET /scans/{id}/export/sarif` -- SARIF 2.1.0 (статика и статическая часть
  MCP): файл для GitHub code scanning, GitLab, IDE.
- `GET /scans/{id}/export/attacks` -- успешные атаки с диалогами (динамика):
  атакующие промпты и ответы агента, а для инъекций -- ещё и подложенный
  payload с перехваченным трафиком прогона.
- `GET /assets/{kind}/{id}/summary` -- сводка-дашборд карточки актива: оценка
  устойчивости, находки по серьёзности, разбивка по типам сканирований.
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlmodel import Session, select

from app import reports, sarif
from app.db import get_session
from app.models import (
    AgentConfig,
    AssetKind,
    InjectionTrial,
    McpAsset,
    Scan,
    ScanStatus,
    SkillAsset,
    TrafficEvent,
)

router = APIRouter(tags=["reports"])

# Сканы этих типов выгружаются как диалоги атак, остальные -- как SARIF.
_DIALOGUE_TYPES = {"indirect_injection", "system_prompt_leak"}


def _get_scan(scan_id: int, session: Session) -> Scan:
    scan = session.get(Scan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Сканирование не найдено")
    return scan


def _json_download(payload: dict, filename: str) -> Response:
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/scans/{scan_id}/report")
def get_scan_report(scan_id: int, session: Session = Depends(get_session)) -> dict:
    """Единый отчёт скана -- его читает страница скана и сводка актива."""
    return reports.build(_get_scan(scan_id, session))


@router.get("/scans/{scan_id}/export/sarif")
def export_sarif(scan_id: int, session: Session = Depends(get_session)) -> Response:
    scan = _get_scan(scan_id, session)
    report = reports.build(scan)
    if report["scan"]["analysis"] == "dynamic":
        raise HTTPException(
            status_code=422,
            detail="SARIF выгружается для статического анализа; для динамики используйте выгрузку диалогов атак",
        )
    document = sarif.build(report)
    return Response(
        content=json.dumps(document, ensure_ascii=False, indent=2),
        media_type="application/sarif+json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="scan-{scan_id}.sarif"'},
    )


def _trial_conversation(trial: InjectionTrial, traffic: list[TrafficEvent]) -> list[dict]:
    """Диалог прогона инъекции: что отправили агенту, что подложил прокси и
    что агент ответил. Перехваченный трафик показывает подмену как есть."""
    point = str(getattr(trial.injection_point, "value", trial.injection_point) or "")
    conversation: list[dict] = []

    if point == "system_prompt":
        if trial.canary:
            conversation.append(
                {
                    "role": "system",
                    "content": f"[в системное сообщение агента прокси вставил метку: {trial.canary}]",
                    "injected": True,
                }
            )
        if trial.payload_text:
            conversation.append({"role": "user", "content": trial.payload_text})
    else:
        if trial.task:
            conversation.append({"role": "user", "content": trial.task})
        if trial.payload_text:
            conversation.append(
                {
                    "role": "tool",
                    "name": trial.target_tool,
                    "content": trial.payload_text,
                    "injected": True,
                    "note": "payload, дописанный прокси в результат инструмента",
                }
            )
    if trial.agent_response:
        conversation.append({"role": "assistant", "content": trial.agent_response})

    for event in traffic:
        if event.direction != "request" or not event.injected:
            continue
        try:
            body = json.loads(event.raw_excerpt or "{}")
        except json.JSONDecodeError:
            continue
        messages = body.get("messages")
        if isinstance(messages, list):
            conversation.append(
                {
                    "role": "_intercepted_request",
                    "content": json.dumps(messages, ensure_ascii=False, indent=2),
                    "note": f"перехваченный запрос к LLM с подменой ({event.injection_target})",
                }
            )
            break
    return conversation


@router.get("/scans/{scan_id}/export/attacks")
def export_attacks(scan_id: int, session: Session = Depends(get_session)) -> Response:
    """Успешные атаки с диалогами. Для инъекций берём прогоны и перехваченный
    трафик из базы (там полный payload и реальная подмена), для DeepTeam и
    PyRIT -- промпт и ответ, сохранённые сканером в результатах."""
    scan = _get_scan(scan_id, session)
    report = reports.build(scan)
    if report["scan"]["analysis"] != "dynamic":
        raise HTTPException(
            status_code=422,
            detail="Диалоги атак есть только у динамического тестирования; для статики используйте SARIF",
        )

    scan_type = report["scan"]["type"]
    attacks: list[dict] = []

    if scan_type in _DIALOGUE_TYPES:
        trials = session.exec(
            select(InjectionTrial)
            .where(InjectionTrial.scan_id == scan_id)
            .where(InjectionTrial.verdict == "vulnerable")
            .order_by(InjectionTrial.id)
        ).all()
        for trial in trials:
            traffic = session.exec(
                select(TrafficEvent).where(TrafficEvent.trial_id == trial.id).order_by(TrafficEvent.id)
            ).all()
            attacks.append(
                {
                    "id": trial.id,
                    "payload_name": trial.payload_name,
                    "payload_family": trial.payload_family,
                    "target_tool": trial.target_tool,
                    "canary": trial.canary,
                    "verdict_reason": trial.verdict_reason,
                    "conversation": _trial_conversation(trial, traffic),
                }
            )
    else:
        for finding in report["findings"]:
            evidence = finding.get("evidence") or {}
            attacks.append(
                {
                    "id": finding["id"],
                    "attack": finding.get("rule_id") or finding["title"],
                    "severity": finding["severity"],
                    "verdict_reason": finding.get("description"),
                    "conversation": evidence.get("conversation") or [],
                }
            )

    payload = {
        "version": reports.REPORT_VERSION,
        "scan": report["scan"],
        "metrics": report["metrics"],
        "rating": report["rating"],
        "rating_label": report["rating_label"],
        "successful_attacks": attacks,
    }
    if not attacks:
        payload["note"] = "Успешных атак не зафиксировано — выгружать диалоги нечего."
    return _json_download(payload, f"scan-{scan_id}-attacks.json")


def _asset_exists(kind: str, asset_id: int, session: Session) -> bool:
    model = {"agent": AgentConfig, "mcp": McpAsset, "skill": SkillAsset}.get(kind)
    return bool(model and session.get(model, asset_id))


@router.get("/assets/{kind}/{asset_id}/summary")
def asset_summary(
    kind: AssetKind,
    asset_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """Сводка-дашборд карточки актива.

    Находки и оценка считаются по **последнему завершённому скану каждого
    типа**: иначе повторные прогоны одного сканера удваивали бы находки.
    Итоговая оценка -- худшая среди типов.
    """
    kind_value = str(getattr(kind, "value", kind))
    if not _asset_exists(kind_value, asset_id, session):
        raise HTTPException(status_code=404, detail="Актив не найден")

    scans = session.exec(
        select(Scan)
        .where(Scan.asset_kind == kind_value)
        .where(Scan.asset_id == asset_id)
        .order_by(Scan.created_at.desc())
    ).all()

    status_counts = {status.value: 0 for status in ScanStatus}
    latest_by_type: dict[str, Scan] = {}
    for scan in scans:
        status_value = str(getattr(scan.status, "value", scan.status))
        status_counts[status_value] = status_counts.get(status_value, 0) + 1
        scan_type = str(getattr(scan.type, "value", scan.type))
        if status_value == ScanStatus.COMPLETED.value and scan_type not in latest_by_type:
            latest_by_type[scan_type] = scan  # список уже отсортирован по дате убывающе

    by_severity = {severity: 0 for severity in reports.SEVERITIES}
    by_scan_type: list[dict] = []
    for scan_type, scan in latest_by_type.items():
        report = reports.build(scan)
        for severity, count in report["metrics"]["by_severity"].items():
            by_severity[severity] += count
        by_scan_type.append(
            {
                "type": scan_type,
                "type_label": report["scan"]["type_label"],
                "analysis": report["scan"]["analysis"],
                "scan_id": scan.id,
                "scan_name": scan.name,
                "finished_at": report["scan"]["finished_at"],
                "rating": report["rating"],
                "rating_label": report["rating_label"],
                "findings_total": report["metrics"]["findings_total"],
                "resistance_rate": report["metrics"]["resistance_rate"],
                "attack_success_rate": report["metrics"]["attack_success_rate"],
                "checks_total": report["metrics"]["checks_total"],
            }
        )
    by_scan_type.sort(key=lambda row: reports.RATING_ORDER.index(row["rating"]), reverse=True)

    rating = reports.worst_rating([row["rating"] for row in by_scan_type])
    return {
        "asset": {"kind": kind_value, "id": asset_id},
        "scans": {"total": len(scans), **status_counts},
        "findings_total": sum(by_severity.values()),
        "by_severity": by_severity,
        "rating": rating,
        "rating_label": reports.RATING_LABELS[rating],
        "by_scan_type": by_scan_type,
        "last_scan_at": reports._iso(scans[0].created_at) if scans else None,
    }
