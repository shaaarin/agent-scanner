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
| `control-api` | FastAPI + SQLModel/PostgreSQL (сервис `postgres`). Единый источник данных: `LLMModel`, `AgentConfig`, `Scan`, `ScanLog`, `TrafficEvent`. Миграции — Alembic на старте. |
| `proxy` | mitmproxy-аддон (`addon.py`). Журналирует трафик агента к LLM и подставляет заголовки идентификации клиента. |
| `scanner-deepteam` (`scanner/deepteam`) | Скан `deep_team`: поднимает агента через `launcher`, гоняет DeepTeam, пишет фазы/журнал/результаты. |
| `scanner-pyrit` (`scanner/pyrit`) | Скан `pyrit_scan`: поднимает агента через `launcher` и атакует его целями Microsoft PyRIT (промпты с конвертерами, RedTeaming, Crescendo), судья — `LLMModel`. |
| `scanner-promptfoo` (`scanner/promptfoo`) | Скан `code_scan`: клонирует репозиторий агента и прогоняет `promptfoo code-scans`. kind/launcher не нужны. |
| `scanner-semgrep` (`scanner/semgrep`) | Скан `ai_code_scan`: клонирует репозиторий агента и прогоняет локальный semgrep по правилам для AI/LLM-кода (`rules/ai-security.yml` + опциональные наборы Registry). kind/launcher и внешние ключи не нужны, код не покидает платформу. |
| `scanner-indirect` (`scanner/indirect`) | Скан `indirect_injection`: поднимает агента через `launcher`, шлёт легитимную задачу и через прокси подкладывает инъекцию в результаты его инструментов (сообщения `role: tool`), оценивая по контрольной метке. |
| `scanner-sysleak` (`scanner/sysleak`) | Скан `system_prompt_leak`: поднимает агента через `launcher`, через прокси вставляет метку в его системное сообщение и шлёт атакующие промпты, проверяя ответ на наличие метки (утечка системного промпта). |
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
- **База мигрируется, не пересоздаётся.** Хранилище — PostgreSQL (сервис
  `postgres`, подключение через `DATABASE_URL`). `control-api` при старте
  делает `alembic upgrade head` (`app/db.py::init_db`). Меняя
  `control-api/app/models.py`, добавьте ревизию в
  `control-api/app/migrations/versions/` (или
  `docker compose exec control-api alembic revision -m "..."`) и
  перезапустите `control-api`. Базовая ревизия — `0001_baseline`
  (замороженный снимок); старые БД автоматически помечаются ей.
  **Никогда не удаляйте том `agent-scanner_control-api-pg-data`.**
  Старый том SQLite `agent-scanner_control-api-data` больше не используется,
  но сохраняется: из него данные переносит
  `control-api/scripts/migrate_sqlite_to_pg.py` (см. `docs/running-locally.md`).
- **Открытые страницы.** Раздел «Активы» (`/assets`, вкладки
  агенты/MCP/skills): активы создаются и хранятся там, сканирование
  создаётся **внутри карточки актива** (`/assets/<kind>/<id>`) — выбор
  сканера и его параметры форма берёт из `GET /scanners`, никаких списков
  опций на фронте. `Scan`-флоу: `POST /scans/{id}/start` (control-api)
  дёргает сканер своего типа, тот пишет `ScanLog`/фазу, UI опрашивает
  `GET /scans/{id}/logs?after_id=...`. API: `/assets`, `/mcp-assets`,
  `/skill-assets`, `/scanners`, `/scans`, `/scans/{id}/logs`,
  `/llm-models`, `/agent-configs`, `/events`, `/events/{id}`,
  `/library/articles`.
- **Реестр сканеров.** Единственное место со связкой «тип → сервис» —
  `control-api/app/scanner_registry.py` (`ScannerRegistration`: вид актива,
  фазы, `requirements` -- свойства актива ("code"/"live"/"deployable"),
  `validate_config` hook). `GET /scanners` отдаёт регистрации вместе с
  живыми config-схемами: каждый сканер описывает поля своего конфига на
  `GET /schema` (типы полей: `string/text/text_list/integer/boolean/enum/
  enum_multi/llm_model/json`), control-api кэширует на 30 с и помечает
  недоступные. С `asset_kind`+`asset_id` -- ещё и применимость к активу
  (`available_for_asset` + `unavailable_reason`; у MCP движки схемы
  фильтруются по режиму цели). Новый сканер = новая папка + сервис в compose
  + регистрация в реестре + `GET /schema` у сервиса + значение `ScanType`.
- **Метки активов.** У активов два свойства, показываемые бейджами в UI:
  «есть код» (исходники: агенты из репозитория, MCP из репо/MCPB, skills) и
  «живой сервис» (remote-агенты и remote-MCP; MCP с настроенным деплоем).
  Источник истины по применимости сканеров -- бекенд (`requirements`),
  бейджи во фронте -- отображение тех же правил.
- **Активы.** Три вида: `agent` (`AgentConfig`), `mcp`
  (`McpAsset`: цель remote/repository/bundle в `config` JSON) и `skill`
  (`SkillAsset`: git-репозиторий или zip-архив BLOB-ом; сканера для skills
  пока нет — запуск вернёт 400/422). Скан ссылается на актив парой
  `asset_kind`/`asset_id`; для агентов синхронно заполняется
  `agent_config_id` — его читают сканеры и launcher, колонка строковая и
  хранит значения (`'agent'`), не имена enum.
- **Remote-агенты.** `AgentConfig.source` — `repository` (по умолчанию,
  сборка через launcher) или `remote`: уже запущенный вне платформы сервис,
  только `remote_base_url` + `remote_headers` (произвольные заголовки
  авторизации, например `Authorization: Bearer ...` или `X-API-Key`) и
  обычный конфиг взаимодействия (api_config/langgraph_config; поля «Порт
  API» и «Переменные окружения» для remote не применяются — это про сборку).
  Раннер deepteam при remote пропускает launcher и сам склеивает base URL с
  путём эндпоинта и подставляет заголовки (`_apply_remote_source`; явные
  заголовки в api_config.headers приоритетнее); создание сканов `code_scan`,
  `indirect_injection`, `system_prompt_leak` для remote-агента отклоняется
  (422): анализу нужен репозиторий, а инъекциям — трафик агента через
  MITM-прокси, которого у remote нет. Колонки-энумы (`AgentConfig.source`,
  `Scan.asset_kind`) объявлены как String и хранят значения enum, не имена.
- **Один сканер — один сервис.** Каждый тип скана выполняет свой сервис из
  `scanner/<имя>` (`scanner-<имя>` в compose) с одинаковым контрактом:
  `GET /health`, `GET /schema`, `POST /run/{scan_id}` (ответ сразу, работа в
  фоне), прогресс/результаты — в control-api через `PATCH /scans/{id}` и
  `POST /scans/{id}/logs`. Тип без сканера в реестре (`agent_skills`)
  запустить нельзя (400). Общий код между сканерами не выносится:
  `control_client.py` (и `target.py` у интерактивных сканеров) у каждого
  свой.
- **MCP-конфигурация.** MCP-цель — это актив (`McpAsset`), а не часть скана:
  при создании скана control-api копирует цель из актива в
  `Scan.config.target`, так что контракт scanner-mcp не меняется, а правки
  актива не переписывают созданные сканы. У актива есть необязательный блок
  `deploy` (порт, команда запуска, env) — как поднять сервер из
  репозитория/MCPB для динамического сканирования; существующие движки его
  не читают, это данные под грядущий деплой. Источники: удалённый сервер
  (`remote`), Git-репозиторий (`repository`) или загруженный `MCPArtifact`
  (`bundle`). MCPB принимается локальным файлом или скачивается сразу по
  публичному HTTPS URI, проверяется как ZIP с корневым `manifest.json` и
  хранится BLOB-ом в PostgreSQL. `scanner_ids` и `timeout_seconds` общие для
  всех источников; пустой `scanner_ids` означает «локальный набор по типу
  цели» (без Snyk). `scanner-mcp` реализован как координатор с отдельными
  контейнерами движков; ad-hoc проверки с inline-кодом (бывшая страница
  «MCP-сканеры») удалены. Код репозитория не запускается.
  Покрытие и тесты — `docs/mcp-testing.md`, справка на сайте — `/help`.
- **Анализ кода — облако Promptfoo.** `scanner-promptfoo` отправляет код
  агента в Promptfoo (ключ `PROMPTFOO_API_KEY` из `.env`); модель анализа
  выбирает Promptfoo, `LLMModel` не участвует. Версия CLI зафиксирована в
  `scanner/promptfoo/Dockerfile`, формат результатов — в
  `docs/code-scan-architecture.md`.
- **Анализ AI-кода — локальный Semgrep.** `scanner-semgrep` выполняет
  `ai_code_scan` без облака: свой набор AI-правил (`rules/ai-security.yml`)
  выполняется всегда, официальные наборы Registry (`p/...`, нужен интернет)
  и пользовательские YAML-правила — по выбору в форме скана. Формат
  `Scan.results` общий с `code_scan` — страницу рендерит тот же компонент
  (`CodeScanResults`, имя движка — поле `engine_label`).
- **Прокси идентифицирует клиента.** На исходящих `chat/completions`
  ставится `User-Agent` (`LLM_CLIENT_USER_AGENT`) и, для `opencode.ai`,
  `x-opencode-session: <SESSION_ID>`. Тело/промпт не переписываются —
  **кроме** сканов, где прокси работает по директиве
  `GET /scans/{id}/injection/active` (уточняется без кэша,
  `proxy/app/injection.py`): `indirect_injection` дописывает payload в
  результат инструмента (`apply`), `system_prompt_leak` вставляет метку в
  системное сообщение (`apply_system`). Куда подкладывать — поле
  `injection_point` директивы. В остальных сканах прокси — только наблюдатель.
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
- **CRUD-страницы в `web/`** (`AgentConfigs.tsx` — вкладка «Агенты» в
  разделе «Активы», `LLMModels.tsx`) — dual-purpose create/edit
  (`editingId`, PUT/PATCH при редактировании). `LLMModel.api_key` при
  редактировании: пустое поле = «не менять» (список всегда возвращает
  маску). Форма создания сканирования — `ScanCreateModal` +
  `ScannerConfigForm`, генерируются из `GET /scanners`.

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
