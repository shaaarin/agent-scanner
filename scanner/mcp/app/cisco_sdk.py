"""Executed inside Cisco's isolated Python environment, never target code."""
import asyncio
import json
import sys
from mcpscanner.core.analyzers.prompt_defense_analyzer import PromptDefenseAnalyzer
from mcpscanner.core.analyzers.readiness.readiness_analyzer import ReadinessAnalyzer

async def main():
    engine, filename = sys.argv[1:]
    analyzer = ReadinessAnalyzer(enable_opa=False, enable_llm_judge=False) if engine == "readiness" else PromptDefenseAnalyzer()
    tools = json.load(open(filename))["tools"]
    entries = []
    for tool in tools:
        content = json.dumps(tool) if engine == "readiness" else (tool.get("description") or tool["name"])
        findings = await analyzer.analyze(content, {"tool_name": tool["name"], "content_type": "description"})
        entries.append({"tool_name": tool["name"], "status": "completed", "findings": {engine: [f.__dict__ for f in findings if f.severity not in {"INFO", "SAFE"}]}})
    print(json.dumps({"scan_results": entries, "requested_analyzers": [engine]}))

asyncio.run(main())
