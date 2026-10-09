# MCP: реализация и проверка

Пользовательская документация находится на сайте `/help` (выбор движка,
форматы источников, примеры, результаты, команды и устранение ошибок).

## Совместимость с feature/mcp-scan-config

Основа — коммит Чернякова `aaf990099c5a9116f7a505f88996f8e966ad0f62`.
Сохранены remote/repository/bundle, загрузка и SQLite-хранение MCPB,
миграции 0001–0004, nullable agent_config_id и расширенная форма создания
MCP-скана. Добавлены source/snapshot, планировщик scanner_ids, новые
сканеры, результаты и справка. Таблицы и том базы не пересоздавались.
Ветка `feature/mcp-testing` создана от feature/mcp-scan-config.
Для дальнейшей разработки используйте отдельную ветку `feature/mcp-testing`.

## Контейнеры и API

`control-api` направляет MCP-сканы в координатор `scanner-mcp`.
Координатор планирует scanner_ids, отправляет каждую задачу в отдельный
scanner-mcp-{engine}, собирает результаты и пишет жизненный цикл скана.
Worker принимает только собственный engine. Каталог `/mcp-scanners`
отображает доступность контейнеров и наличие ключа Snyk.
Рабочие контейнеры не публикуют порты хоста, имеют лимиты CPU/памяти/PID,
cap_drop ALL, no-new-privileges. Подпроцессы ограничены временем/выводом.

Исходники анализируются без исполнения. Архивы ограничены размером,
количеством файлов, путями и запретом symlink. Публичный Git клонируется
по HTTPS без редиректов и запуска install scripts. Приватный Git с токеном
пока отклоняется явно. URL к внутренним компонентам платформы,
link-local и metadata запрещены; частные тестовые MCP-сети допускаются.
Это локальный стенд, не многопользовательская система для недоверенных
пользователей: сетевой egress и DNS rebinding требуют отдельного усиления.

## Воспроизводимые проверки

```sh
docker compose -f compose.local.yml --profile test up -d --build
python3 scripts/smoke_mcp.py
```

Скрипт использует настоящие API, CLI/SDK upstream и живой FastMCP-сервер.
Проверяются четыре опасные операции Python, безопасный контроль, SSRF,
TypeScript eval, точность вне MCP-декоратора, MCPB upload/storage/scan,
Cisco YARA по каталогу и живому MCP, Readiness, Prompt Defense,
MCPRadar по каталогу и живому MCP, успешные реальные echo/add и намеренно
нарушенное ожидание ответа. Отчёт с ID сканов: mcp-smoke-results.json.
Snyk не тестируется без ключа; в результатах это нельзя считать успехом.

## Исследование методов

- [Cisco MCP Scanner](https://github.com/cisco-ai-defense/mcp-scanner),
  4.8.6: YARA через CLI, Readiness и Prompt Defense через SDK. Локальные
  эвристики каталога. AI Defense API и LLM-анализаторы не включены.
- [MCPRadar](https://github.com/yatuk/mcpradar), 1.0.0rc4 из PyPI:
  upstream RuleEngine для описаний и input/output schemas инструментов.
  MCP-каталог собирается SDK платформы с пагинацией и ограничениями.
  Новые возможности main-ветки, prompts/resources, supply chain и
  runtime probes не подключены. Не приписывать старой версии новые API.
- [Snyk Agent Scan](https://github.com/snyk/agent-scan), 0.6.8: облачная
  оценка каталога. Только remote, SNYK_TOKEN и явный allow_cloud.
  Пользовательские headers пока не поддерживаются и отклоняются явно.
- [Semgrep](https://semgrep.dev/docs/writing-rules/overview), 1.180.0:
  шесть собственных AST-правил, Python и JS/TS MCP-функции. Без
  межфайлового taint; совпадение требует ручной проверки потока данных.
- [MCP tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools):
  initialize/list_tools, сравнение каталога и явные probes call_tool.
  Это контролируемые интеграционные проверки, не автоматический пентест
  и не оценка устойчивости LLM-агента к prompt injection.

Эвристики описаний и AST покрывают разные поверхности. Применять их
совместно и подтверждать наиболее важные находки динамическими сценариями.
Нулевой отчёт не доказывает безопасность; ошибка анализа не является чистым
результатом. В интерфейсе выводится область покрытия каждого движка.
