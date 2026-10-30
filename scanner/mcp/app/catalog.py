import os

ENGINES = [
    dict(id="mcpradar", name="MCPRadar", kind="metadata", version="1.0.0rc4", description="Локальные правила MCPRadar: отравление описаний, инъекции и злоупотребление схемами инструментов. Без вызовов инструментов.", source="https://github.com/yatuk/mcpradar", cloud=False, modes=["snapshot", "remote", "bundle"]),
    dict(id="cisco_yara", name="Cisco MCP Scanner · YARA", kind="metadata", version="4.8.6", description="Локальные сигнатуры инъекций и опасных инструкций в каталоге инструментов.", source="https://github.com/cisco-ai-defense/mcp-scanner", cloud=False, modes=["snapshot", "remote", "bundle"]),
    dict(id="cisco_readiness", name="Cisco MCP Scanner · Readiness", kind="readiness", version="4.8.6", description="Эвристики эксплуатационной готовности. Замечания не являются доказанными уязвимостями.", source="https://github.com/cisco-ai-defense/mcp-scanner", cloud=False, modes=["snapshot", "remote", "bundle"]),
    dict(id="cisco_prompt_defense", name="Cisco MCP Scanner · Prompt Defense", kind="metadata", version="4.8.6", description="Проверка наличия защитных инструкций. Не доказывает исполнение защиты сервером.", source="https://github.com/cisco-ai-defense/mcp-scanner", cloud=False, modes=["snapshot", "remote", "bundle"]),
    dict(id="snyk", name="Snyk Agent Scan", kind="metadata", version="0.6.8", description="Облачный анализ каталога работающего MCP. Нужны SNYK_TOKEN и согласие на передачу каталога.", source="https://github.com/snyk/agent-scan", cloud=True, modes=["remote"]),
    dict(id="mcp_dynamic", name="MCP · Динамическое тестирование", kind="dynamic", version="1.1", description="Инициализация, каталог, явные пробные вызовы и опциональные автоматические Python/JavaScript-проверки строковых аргументов по inputSchema. Для MCPB — развёртывание по манифесту и stdio.", source="https://modelcontextprotocol.io/specification/2025-11-25/server/tools", cloud=False, modes=["remote", "bundle"]),
    dict(id="semgrep", name="MCP SAST · Semgrep", kind="sast", version="1.180.0", description="Шесть локальных AST-правил для MCP: выполнение кода/команд, пути, SSRF и выдача окружения (Python, JavaScript/TypeScript). Находки требуют проверки.", source="https://semgrep.dev/docs/writing-rules/overview", cloud=False, modes=["source", "repository", "bundle"]),
]

def catalog():
    return [dict(e, available=e["id"] != "snyk" or bool(os.getenv("SNYK_TOKEN")), reason="Задайте SNYK_TOKEN в .env" if e["id"] == "snyk" and not os.getenv("SNYK_TOKEN") else None) for e in ENGINES]
