"""Run the pinned upstream rule engine without executing MCP tools."""
import json
import sys
from dataclasses import asdict
from mcpradar.scanner.rules import RuleEngine
from mcpradar.scanner.report import ToolInfo, Severity

catalog = json.load(open(sys.argv[1]))
engine = RuleEngine(min_severity=Severity.LOW)
findings = []
for tool in catalog["tools"]:
    info = ToolInfo(name=tool["name"], description=tool.get("description", ""), input_schema=tool.get("inputSchema", {}), output_schema=tool.get("outputSchema", {}))
    for finding in engine.analyze(info):
        findings.append(asdict(finding))
print(json.dumps(dict(findings=findings, tools_checked=len(catalog["tools"]))))
