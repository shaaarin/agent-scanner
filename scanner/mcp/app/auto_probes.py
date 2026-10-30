"""Bounded, schema-driven MCP checks; no server names, CVE IDs or file paths.

An exception whose message is computed from character codes is the execution
oracle. The literal marker never appears in the argument, so echoing a rejected
input does not confirm code execution. Payloads perform no I/O or shell calls.
"""
import asyncio
import copy
import json
import re
import secrets
import time

from jsonschema import Draft202012Validator

MAX_CALLS = 20
CALL_TIMEOUT = 5
_MUTATING = re.compile(r"(?:^|_)(?:write|save|create|update|delete|remove|modify|set|upload|install|commit|checkout|reset|execute|exec|run|shell|spawn|kill|stop)(?:_|$)")


def _schema(schema, root, depth=0):
    if depth > 8 or not isinstance(schema, dict):
        raise ValueError("Слишком сложная схема аргумента")
    if "$ref" in schema:
        ref = schema["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            raise ValueError("Поддерживаются только локальные ссылки JSON Schema")
        resolved = root
        for part in ref[2:].split("/"):
            resolved = resolved[part.replace("~1", "/").replace("~0", "~")]
        return _schema(resolved, root, depth+1)
    if "anyOf" in schema or "oneOf" in schema:
        choices = schema.get("anyOf", schema.get("oneOf"))
        choice = next((x for x in choices if x.get("type") != "null"), None)
        return _schema(choice, root, depth+1)
    return schema


def _minimal(schema, root, depth=0):
    if depth > 5:
        raise ValueError("Слишком глубокая схема аргументов")
    schema = _schema(schema, root)
    if "default" in schema:
        return copy.deepcopy(schema["default"])
    if "const" in schema:
        return copy.deepcopy(schema["const"])
    if schema.get("enum"):
        return copy.deepcopy(schema["enum"][0])
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((x for x in kind if x != "null"), "null")
    if kind == "object" or "properties" in schema:
        props = schema.get("properties", {})
        return {name: _minimal(props[name], root, depth+1) for name in schema.get("required", [])}
    if kind == "array":
        count = schema.get("minItems", 0)
        if count > 5:
            raise ValueError("Схема требует слишком большой массив")
        return [_minimal(schema.get("items", {}), root, depth+1) for _ in range(count)]
    if kind in {"number", "integer"}:
        return schema.get("minimum", 0)
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    if kind == "string":
        return "test".ljust(min(schema.get("minLength", 0), 100), "x")
    raise ValueError("Неизвестный тип аргумента")


def _payloads(marker):
    encoded = marker.encode().hex()
    yield "python", f"(_ for _ in ()).throw(__import__('builtins').ValueError(__import__('builtins').bytes.fromhex('{encoded}').decode()))"
    codes = ",".join(str(ord(c)) for c in marker)
    yield "javascript", f"(()=>{{throw new Error(String.fromCharCode({codes}))}})()"


def build_probes(tools):
    probes, skipped = [], []
    for tool in tools:
        name = tool["name"]
        words = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower().replace("-", "_")
        annotations = tool.get("annotations") or {}
        if _MUTATING.search(words) or annotations.get("destructiveHint") is True or annotations.get("readOnlyHint") is False:
            skipped.append({"tool": name, "reason": "Изменяющий состояние или исполняющий команды инструмент"})
            continue
        root = tool.get("inputSchema", {})
        try:
            resolved = _schema(root, root)
            props = resolved.get("properties", {})
            validator = Draft202012Validator(root)
            # No remote schema resolution or extra properties are generated.
            if not props or any(not isinstance(p, dict) for p in props.values()):
                raise ValueError("Нет поддерживаемых свойств в inputSchema")
            nodes = list(_nodes(root))
            if any(isinstance(node.get(key), str) and not node[key].startswith("#/") for node in nodes for key in ("$ref", "$dynamicRef", "$recursiveRef")):
                raise ValueError("Схема содержит внешнюю ссылку")
            if any("pattern" in node or "patternProperties" in node for node in nodes):
                raise ValueError("Схема с регулярными выражениями не используется для автоподбора")
            base = _minimal(resolved, root)
            added = 0
            for field, raw_schema in props.items():
                spec = _schema(raw_schema, root)
                kind = spec.get("type")
                if (kind != "string" and not (isinstance(kind, list) and "string" in kind)) or "enum" in spec or "const" in spec:
                    continue
                for language in ("python", "javascript"):
                    marker = "MCP_AUTO_" + secrets.token_hex(12)
                    payload = dict(_payloads(marker))[language]
                    args = {**base, field: payload}
                    if not validator.is_valid(args):
                        continue
                    assert marker not in payload
                    probes.append({"tool": name, "arguments": args, "field": field, "language": language, "marker": marker})
                    added += 1
                    if len(probes) == MAX_CALLS:
                        return probes, skipped
            if not added:
                skipped.append({"tool": name, "reason": "Нет свободных строковых аргументов с подходящей схемой"})
        except (ValueError, KeyError, TypeError, RecursionError) as exc:
            skipped.append({"tool": name, "reason": str(exc)[:300]})
    return probes, skipped


def _nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _nodes(child)


async def run_automatic(session, tools, deadline):
    probes, skipped = build_probes(tools)
    checks, findings = [], []
    summary = {"generated": len(probes), "executed": 0, "errors": 0, "budget_skipped": 0, "call_limit": MAX_CALLS, "limit_reached": len(probes) == MAX_CALLS, "tools_in_catalog": len(tools), "skipped_tools": skipped}
    for i, probe in enumerate(probes):
        remaining = deadline - time.monotonic()
        if remaining < 1:
            summary["budget_skipped"] = len(probes)-i
            checks.append({"name": "Оставшиеся автоматические проверки", "status": "skipped", "evidence": "Достигнут лимит времени; эти вызовы не выполнены"})
            break
        label = f"Автопроверка {probe['language']}: {probe['tool']}.{probe['field']}"
        try:
            result = await asyncio.wait_for(session.call_tool(probe["tool"], probe["arguments"]), timeout=min(CALL_TIMEOUT, remaining))
            summary["executed"] += 1
            data = result.model_dump(mode="json", by_alias=True, exclude_none=True)
            text = json.dumps(data, ensure_ascii=False)
            confirmed = probe["marker"] in text
            position = max(0, text.find(probe["marker"])-200) if confirmed else 0
            evidence = {"arguments": probe["arguments"], "computed_marker": probe["marker"], "is_error": data.get("isError", False), "response_excerpt": text[position:position+2000]}
            evidence_text = json.dumps(evidence, ensure_ascii=False)[:4000]
            checks.append({"name": label, "status": "failed" if confirmed else "passed", "evidence": evidence_text})
            if confirmed:
                findings.append({"rule_id": "mcp.dynamic.argument-code-execution." + probe["language"], "severity": "high",
                    "title": f"Подтверждено выполнение {probe['language']} из строкового аргумента", "target": probe["tool"],
                    "evidence": evidence_text, "category": "dynamic", "confidence": "HIGH",
                    "recommendation": "Сверьте контракт инструмента: вычисление кода может быть намеренной возможностью. Для данных используйте парсер и разрешённые операции; для исполнения кода проверьте изоляцию. Номер CVE автоматически не определяется."})
        except Exception as exc:
            summary["errors"] += 1
            checks.append({"name": label, "status": "error", "evidence": f"Вызов не завершён: {type(exc).__name__}: {str(exc)[:500]}"})
    if not probes:
        checks.append({"name": "Автоматические проверки аргументов", "status": "skipped", "evidence": "Нет подходящих инструментов/схем; отсутствие вызовов не означает безопасность сервера"})
    return {"checks": checks, "findings": findings, "automatic_checks": summary}
