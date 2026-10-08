# Agent Scanner — карта для разработки

Платформа для проверки безопасности LLM-агентов с вызовом инструментов:
динамическое тестирование атаками, статический анализ кода агента и перехват
реального трафика агента к LLM.

**Перед нетривиальными изменениями прочитайте `docs/architecture.md` и
`docs/running-locally.md`.** Этот файл — карта, а не замена им.

## Как подключается тестируемый агент — прочитать первым

**Ноль изменений в агенте.** Его реальные LLM-креды (`OPENAI_API_KEY`,
`OPENAI_BASE_URL` и т.п.) не трогаются. Платформа прозрачно перехватывает
исходящий HTTPS на сетевом уровне: Pod агента получает
`ca-trust-setup` (подмена системного trust-store) + `net-setup`
(iptables REDIRECT) initContainer'ы и сайдкар `mitm-proxy`
(`proxy/addon.py`, mitmproxy), который терминирует и переподписывает
соединение. Это **заменило** прежний дизайн с явным `base_url` — если где-то
встретите «направьте `OPENAI_BASE_URL` на прокси», это устарело.

## Сервисы (каждый — свой контейнер)

| Сервис | Роль |
|---|---|
| `control-api` | FastAPI + SQLModel/SQLite. Единый источник данных: `LLMModel`, `AgentConfig`, `Scan`, `ScanLog`, `TrafficEvent`. Миграции — Alembic на старте. |
| `proxy` | mitmproxy-аддон (`addon.py`). Журналирует трафик агента к LLM и подставляет заголовки идентификации клиента. |
| `scanner-deepteam` (`scanner/deepteam`) | Скан `deep_team`: поднимает агента через `launcher`, гоняет DeepTeam, пишет фазы/журнал/результаты. |
| `scanner-promptfoo` (`scanner/promptfoo`) | Скан `code_scan`: клонирует репозиторий агента и прогоняет `promptfoo code-scans`. kind/launcher не нужны. |
| `launcher` | Собирает образ агента в кластере (git-clone + Kaniko) и запускает Pod с MITM-сайдкаром, по kubeconfig, без Docker-сокета. |
| `web` | React/Vite дашборд. **Весь текст интерфейса — на русском**, новый текст тоже. |
| `control-api-mitm-bridge` / `launcher-mitm-bridge` | `alpine/socat`-форвардеры, владеющие опубликованным портом вместо dual-homed сервисов (quirk WSL2, см. ниже). |

Каталоги `generator/` и `interactor/` — **легаси** прежней архитектуры
(кампании, шаблоны, fuzz/tree). В `docker-compose.yml` их нет, эндпоинтов под
них в control-api тоже нет. Не оживляйте их без явной задачи.

## Соглашения

- **Никаких моков LLM.** Любой вызов — тестируемый агент, модель-судья
  DeepTeam — идёт в реальный OpenAI-совместимый провайдер из `.env`
  (`LLM_PROVIDER_BASE_URL`/`LLM_PROVIDER_API_KEY`/`LLM_PROVIDER_MODEL`).
  Результаты недетерминированы по замыслу. Не добавляйте mock-заглушки.
- **Учётные данные в открытом виде** — принятый техдолг MVP, не «фиксить»
  попутно: `LLMModel.api_key`, `AgentConfig.git_access_token`,
  `AgentConfig.env_vars`.
- **База мигрируется, не пересоздаётся.** `control-api` при старте делает
  `alembic upgrade head` (`app/db.py::init_db`). Меняя
  `control-api/app/models.py`, добавьте ревизию в
  `control-api/app/migrations/versions/` (или
  `docker compose exec control-api alembic revision -m "..."`) и
  перезапустите `control-api`. Базовая ревизия — `0001_baseline`
  (замороженный снимок); старые БД автоматически помечаются ей.
  **Никогда не удаляйте том `agent-scanner_control-api-data`.**
- **Открытые страницы.** `Scan`-флоу: `POST /scans/{id}/start` (control-api)
  дёргает сканер своего типа, тот пишет `ScanLog`/фазу, UI опрашивает
  `GET /scans/{id}/logs?after_id=...`. API: `/scans`, `/scans/{id}/logs`,
  `/llm-models`, `/agent-configs`, `/events`, `/events/{id}`,
  `/library/articles`.
- **Один сканер — один сервис.** Каждый тип скана выполняет свой сервис из
  `scanner/<имя>` (`scanner-<имя>` в compose) с одинаковым контрактом:
  `GET /health`, `POST /run/{scan_id}` (ответ сразу, работа в фоне),
  прогресс/результаты — в control-api через `PATCH /scans/{id}` и
  `POST /scans/{id}/logs`. Связка «тип → сервис» — `SCANNERS` в
  `control-api/app/api/scans.py`; тип без сканера (`mcp`, `agent_skills`)
  запустить нельзя (400). Новый сканер = новая папка + сервис в compose +
  строка в `SCANNERS` + значение `ScanType` + фазы/результаты в `web`.
  Общий код между сканерами не выносится: `control_client.py` у каждого свой.
- **MCP-конфигурация.** Скан `mcp` не связан с `AgentConfig`
  (`Scan.agent_config_id = null`). Его `Scan.config.target` описывает один из
  источников: удалённый сервер (`remote`), Git-репозиторий (`repository`) или
  загруженный `MCPArtifact` (`bundle`). MCPB принимается локальным файлом или
  скачивается сразу по публичному HTTPS URI, проверяется как ZIP с корневым
  `manifest.json` и хранится BLOB-ом в SQLite. `scanner_ids` и
  `timeout_seconds` общие для всех источников; пустой `scanner_ids` означает
  «все доступные проверки». Клонирование, установка и запуск относятся к
  будущему `scanner-mcp`; пока скан можно настроить и сохранить, но нельзя
  запустить.
- **Анализ кода — облако Promptfoo.** `scanner-promptfoo` отправляет код
  агента в Promptfoo (ключ `PROMPTFOO_API_KEY` из `.env`); модель анализа
  выбирает Promptfoo, `LLMModel` не участвует. Версия CLI зафиксирована в
  `scanner/promptfoo/Dockerfile`, формат результатов — в
  `docs/code-scan-architecture.md`.
- **Прокси идентифицирует клиента.** На исходящих `chat/completions`
  ставится `User-Agent` (`LLM_CLIENT_USER_AGENT`) и, для `opencode.ai`,
  `x-opencode-session: <SESSION_ID>`. Тело/промпт не переписываются.
  **Меняя `proxy/`, обязательно пересоберите и запушьте образ в локальный
  реестр** (`docker compose build proxy && docker tag agent-scanner-proxy:latest
  localhost:5001/agent-scanner-proxy:latest && docker push ...`): сайдкар
  Pod'а тянет фиксированный тег из реестра `kind`, и без пуша ваши правки
  просто не доедут до агента (свежий остаётся только у compose-сервиса
  `proxy`).
- **Библиотека знаний** — это `library/**/*.md`, монтируется в control-api
  read-only и читается на лету; добавление файла не требует пересборки.
  Категория = имя папки, метаданные = YAML-frontmatter.
- **Роутинг сборки агента.** `AgentConfig` build flow: clone → чтение
  `env_example_path` (дозаполнение отсутствующих `env_vars` дефолтами репо,
  явные значения приоритетнее) → сборка `dockerfile_path` через Kaniko
  (контекст — всегда корень репо) → запуск с `env_vars` и авто-проброс
  `api_port` через `NodePort` с прописыванием адреса в
  `api_config.url`/`langgraph_config.base_url`.
- **`git_access_token`** встраивается в clone-URL (`launcher/app/git_auth.py`),
  только HTTPS. Известная утечка: при неудачном клоне URL с токеном попадает
  в логи init-контейнера — задокументировано, не исправлено.
- **CRUD-страницы в `web/`** (`AgentConfigs.tsx`, `LLMModels.tsx`,
  `Scans.tsx`) — dual-purpose create/edit (`editingId`, PUT/PATCH при
  редактировании). `LLMModel.api_key` при редактировании: пустое поле =
  «не менять» (список всегда возвращает маску).

## Локальная разработка

```
cp .env.example .env   # заполнить LLM_PROVIDER_*
docker compose up -d --build
```

`launcher`/`scanner-deepteam` требуют Kubernetes-кластер (агенты собираются и
запускаются как Pod'ы; `scanner-promptfoo` работает без кластера) — разовая настройка `kind` в
`docs/running-locally.md`. Если `kind`/`kubectl` нет в `PATH`, проверьте
`~/bin` прежде чем устанавливать заново.

Перед первым запуском агента положите образ прокси в локальный реестр под
фиксированным тегом `kind-registry:5000/agent-scanner-proxy:latest` (см.
`docs/running-locally.md`).

**Автотестов нет.** Проверка живая: поднять нужные сервисы (и `kind` для
launcher/scanner-deepteam), прогнать реальный HTTP/k8s сценарий, посмотреть
`control-api` `/events`, логи и `kubectl get pods`/`logs`. Придерживайтесь
этого, не добавляйте тест-фреймворк без запроса.

## Особенности окружения (WSL2/Docker Desktop)

- Сервис, подключённый одновременно к default-сети Compose и сети `kind`,
  получает **нестабильный опубликованный порт** (reset/`ERR_EMPTY_RESPONSE`,
  при этом внутри сети всё работает). Поэтому `control-api` не подключён к
  `kind` (его порт постоянно дёргает браузер), а `launcher` — подключён, но
  его опубликованным портом владеет `launcher-mitm-bridge` (`alpine/socat`).
  Если порт всё же «поплыл» — обращайтесь к сервису изнутри:
  `docker compose exec <service> python3 -c "import httpx; print(httpx.get('http://localhost:8000/health').text)"`.
- Контекст сборки Kaniko — всегда корень репозитория;
  `AgentConfig.dockerfile_path` лишь указывает, где лежит Dockerfile (как
  `docker build -f`).
