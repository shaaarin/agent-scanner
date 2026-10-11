# Локальный MCP-стенд

Основа: `feature/mcp-scan-config`, коммит Алексея Чернякова
`aaf990099c5a9116f7a505f88996f8e966ad0f62`.
В GitLab создана отдельная ветка `feature/mcp-testing` от этого коммита.
Рабочая ветка для дальнейшей разработки — `feature/mcp-testing`.
Для команд Git нужен настроенный HTTPS-доступ или SSH-ключ.

```sh
git clone --branch feature/mcp-testing https://git.miem.hse.ru/2303/agent-scanner.git
cd agent-scanner
```

```sh
docker compose -f compose.local.yml --profile test up -d --build
python3 scripts/smoke_mcp.py
```

- Интерфейс: http://localhost:4173/mcp-scanners
- Справка с поиском: http://localhost:4173/help
- API: http://localhost:8000/docs
- Отчёт прогона: `docs/mcp-smoke-results.json`

Стек содержит web, control-api, координатор scanner-mcp и семь отдельных
контейнеров движков: Cisco YARA/Readiness/Prompt Defense, MCPRadar, Snyk,
Semgrep и динамические MCP-проверки. Образ общий, процессы и окружения
контейнеров разделены. SNYK_TOKEN передаётся только в scanner-mcp-snyk.
Тестовый MCP-сервер поднимается профилем test. Внешние порты привязаны
к loopback. База сохранена в `agent-scanner_control-api-data`.

Без облачных ключей работают все локальные движки. Snyk требует SNYK_TOKEN
и явное согласие на передачу каталога. Проверки Snyk с облаком в локальный
прогон не включены. Другие сканеры агентов (DeepTeam/Promptfoo) запускаются
по прежней инструкции `docs/running-locally.md`.

```sh
docker compose -f compose.local.yml ps
docker compose -f compose.local.yml logs --tail=100 scanner-mcp-mcpradar
docker compose -f compose.local.yml stop
```

Не удаляйте том базы данных. После изменения исходников повторите сборку.
