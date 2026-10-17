"""Выгрузка находок в SARIF 2.1.0.

Формат понимают GitHub code scanning, GitLab, IDE и большинство SAST-дашбордов,
поэтому отчёт статического анализа отдаётся именно в нём. На вход идёт уже
унифицированный отчёт (`app/reports.py::build`), так что Promptfoo, Semgrep и
статическая часть MCP выгружаются одинаково.

Соответствие уровней: critical/high -> error, medium -> warning,
low/info -> note (в SARIF всего три уровня, serverity кладём в properties).
"""
import hashlib
from typing import Optional

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"

_LEVELS = {"critical": "error", "high": "error", "medium": "warning", "low": "note", "info": "note"}


def _level(severity: str) -> str:
    return _LEVELS.get(severity, "warning")


def _rule_id(finding: dict) -> str:
    """Идентификатор правила.

    Свой у сканера (semgrep, MCP-движки) используем как есть. Promptfoo
    правил не возвращает -- тогда идентификатор выводим из текста находки:
    иначе разные проблемы схлопнулись бы в одно правило, и потребители
    SARIF (GitHub code scanning и прочие) показали бы их одним алертом.
    """
    rule_id = finding.get("rule_id")
    if rule_id:
        return str(rule_id)
    category = str(finding.get("category") or "finding")
    title = str(finding.get("title") or "")
    if not title:
        return category
    digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]
    return f"{category}/{digest}"


def _location(finding: dict) -> Optional[dict]:
    location = finding.get("location") or {}
    file_path = location.get("file")
    if not file_path:
        return None
    region: dict = {}
    if location.get("start_line"):
        region["startLine"] = int(location["start_line"])
        end_line = location.get("end_line") or location["start_line"]
        if int(end_line) >= int(location["start_line"]):
            region["endLine"] = int(end_line)
    physical: dict = {"artifactLocation": {"uri": str(file_path).lstrip("/")}}
    if region:
        physical["region"] = region
    return {"physicalLocation": physical}


def build(report: dict) -> dict:
    """Унифицированный отчёт -> документ SARIF."""
    findings = report.get("findings") or []
    scan = report.get("scan") or {}
    engine = report.get("engine") or {}

    # Описания правил: по одному на уникальный rule_id.
    rules: dict[str, dict] = {}
    for finding in findings:
        rule_id = _rule_id(finding)
        if rule_id in rules:
            continue
        rule: dict = {
            "id": rule_id,
            "name": rule_id,
            "shortDescription": {"text": str(finding.get("title") or rule_id)[:200]},
            "defaultConfiguration": {"level": _level(str(finding.get("severity")))},
            "properties": {"security-severity-category": finding.get("severity"), "tags": [finding.get("category")]},
        }
        if finding.get("recommendation"):
            rule["help"] = {"text": str(finding["recommendation"])}
        rules[rule_id] = rule

    results = []
    for finding in findings:
        message = str(finding.get("description") or finding.get("title") or "")
        entry: dict = {
            "ruleId": _rule_id(finding),
            "level": _level(str(finding.get("severity"))),
            "message": {"text": message or "Находка без описания"},
            "properties": {
                "severity": finding.get("severity"),
                "category": finding.get("category"),
                "scanId": scan.get("id"),
                "scanType": scan.get("type"),
            },
        }
        location = _location(finding)
        # SARIF допускает результат без локации (динамические находки), но
        # большинство потребителей ждёт хотя бы пустой список.
        entry["locations"] = [location] if location else []
        evidence = finding.get("evidence") or {}
        if evidence.get("detail"):
            entry["properties"]["evidence"] = str(evidence["detail"])[:10000]
        results.append(entry)

    tool_name = str(engine.get("name") or scan.get("type_label") or "agent-scanner")
    driver: dict = {
        "name": f"agent-scanner/{tool_name}",
        "informationUri": "https://git.miem.hse.ru/2303/agent-scanner",
        "rules": list(rules.values()),
    }
    if engine.get("version"):
        driver["version"] = str(engine["version"])

    invocation: dict = {"executionSuccessful": scan.get("status") == "completed"}
    if scan.get("started_at"):
        invocation["startTimeUtc"] = scan["started_at"]
    if scan.get("finished_at"):
        invocation["endTimeUtc"] = scan["finished_at"]

    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {"driver": driver},
                "invocations": [invocation],
                "results": results,
                "properties": {
                    "scanName": scan.get("name"),
                    "assetKind": scan.get("asset_kind"),
                    "assetId": scan.get("asset_id"),
                    "rating": report.get("rating"),
                    "metrics": report.get("metrics"),
                },
            }
        ],
    }
