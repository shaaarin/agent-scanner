# Анализ безопасности Agent Skills — архитектура

Как устроен тип скана `agent_skills` (сервис `scanner-skills`). Все решения
с обоснованиями (D-01…D-52), риски и журнал работ — в
[`SKILLSS.md`](../SKILLSS.md) в корне репозитория; этот документ — карта
того, что получилось. `docs/agent-skills-scanning-plan.md` — исходный план,
во многом устарел (архивы-сущности, загрузка, LLM).

## Суть

Навык (Agent Skill) — папка с `SKILL.md` (YAML-frontmatter + инструкции для
модели) и, возможно, скриптами и ресурсами. Навык исполняется агентом с его
правами, поэтому вредоносный навык — это закрепление в системе, кража
секретов, отправка данных наружу или инъекция в инструкции.

Платформа проверяет навыки **статически**: ничего не запускает, ни один
файл навыка не исполняется. Анализ делают два готовых open-source движка —
**Cisco AI Defense skill-scanner 2.1.0** и **NVIDIA SkillSpector 2.11.2**
(без LLM), — оба со своими YARA-правилами платформы, плюс небольшая
проверка frontmatter. Итоговый вердикт `pass` / `review` / `block` по
каждому навыку и по скану считает **платформа**, вердикты движков —
справочные.

Для пользователя это сканер «[статический анализ] Agent Skills» в карточке
skill-актива (`/assets/skill/<id>`): форма из `GET /scanners` (выбор
движков), кнопка запуска, живой журнал, отчёт на странице скана.

## Источник навыков

Источник — актив `SkillAsset` (вкладка «Skills» в разделе «Активы»):
git-репозиторий или zip-архив, хранящийся BLOB-ом в PostgreSQL. Лимиты
загрузки zip — в `control-api/app/api/skill_assets.py` (50 МиБ, 5000 файлов,
250 МиБ распакованного; `..`, абсолютные пути и симлинки → 422).

При создании скана control-api копирует источник в `Scan.config.source`
(как цель MCP в `target`), так что правка актива не меняет созданный скан:

- zip → `{kind: "zip", asset_id, archive_filename, archive_sha256}`; байты
  сканер берёт из `GET /skill-assets/{id}/content` и сверяет sha256;
- git → `{kind: "repository", git_repo_url, git_ref, git_access_token}`.
  Токен виден в `GET /scans` — тот же принятый техдолг, что у MCP
  repository.

`Scan.config` целиком: `{"engines": ["cisco", "skillspector"], "source": {...}}`.
Пустой `engines` — оба движка. Ключ `eval_llm_model_id` зарезервирован под
LLM-режим: сейчас сканер его игнорирует и пишет об этом в журнал.

## Как проходит скан

`POST /scans/{id}/start` → `scanner-skills` `POST /run/{id}` → фоновый поток
(`app/runner.py`). Фазы (реестр в `control-api/app/scanner_registry.py`):

1. **В очереди** — одновременно выполняются не больше
   `SCAN_MAX_CONCURRENT` (2) сканов, остальные ждут; время в очереди в
   общий таймаут не входит.
2. **Инициализация** — проверка типа скана, вида актива, конфига; разбор
   движков.
3. **Получение исходников** (`app/sources.py`):
   - zip: скачивание потоком (≤ 50 МиБ), сверка sha256, безопасная
     распаковка (`app/archive.py`): до записи на диск и по реально
     прочитанным байтам проверяются `..`/абсолютные пути/`\`/повторы путей,
     симлинки, шифрование, число записей, объём, сжатие записи > 100:1
     (только у записей > 1 МиБ). Файлы пишутся без exec-бита. Нарушение —
     **отказ архива**: скан `completed`, вердикт `block`, движки не
     запускаются;
   - git (`app/repo.py`, `app/git_auth.py`): `clone --depth 1`, только
     http/https, без сабмодулей и hooks, `core.symlinks=false`, `.git`
     удаляется. Превышение лимитов размера у репозитория — `failed`
     («сузьте актив»), а не `block`: это не признак атаки;
   - поиск навыков: папка с `SKILL.md` (не симлинк); вложенный `SKILL.md` —
     часть внешнего навыка; `.git`, `node_modules`, `__pycache__`, `.venv`
     не обходятся. Имя — `name` из frontmatter, иначе имя папки. Нет ни
     одного навыка — `failed`; больше `SCAN_MAX_SKILLS` (50) — `failed`.
4. **Статический анализ** (`app/analysis.py`) — навыки по очереди, движки
   одного навыка параллельно, плюс проверка frontmatter. После каждого
   навыка — строка журнала «[i/n] имя: движок — N находок, макс. X, T с».
5. **Сохранение результатов** (`app/report.py`) — вердикт и отчёт в
   `Scan.results`.
6. **Завершено**.

Таймауты: `SCAN_ENGINE_TIMEOUT` (300 с) на один запуск движка по одному
навыку — по истечении убивается вся группа процессов (`app/procs.py`), а
движок «не отработал»; `SCAN_TOTAL_TIMEOUT` (30 мин) на весь скан —
`failed`. Скан, прерванный перезапуском сервиса, при старте переводится в
`failed`. Рабочая папка скана удаляется в любом исходе.

Упал один движок — скан `completed`, но `complete: false` и предупреждение
в журнале и отчёте. Не отработал ни один движок — `failed` («Ни один движок
не отработал: …»).

## Движки

Каждый движок — отдельный venv в образе (`/opt/engines/cisco`,
`/opt/engines/skillspector`), запускается CLI в отдельном процессе
(`app/engines/`):

| | Cisco skill-scanner | NVIDIA SkillSpector |
|---|---|---|
| Версия | `cisco-ai-skill-scanner==2.1.0` (PyPI) | `v2.11.2`, git-тег + проверка SHA коммита |
| Команда | `scan --use-behavioral --trusted-rule-pack <пак> --format json --output` | `scan --no-llm --yara-rules-dir <правила> -f json -o` |
| Успех | код 0 + валидный JSON | код 0 или 1 («риск выше порога») + валидный JSON; 2 — ошибка |
| Сеть | не нужна | OSV.dev для проверки зависимостей |

Общее для адаптеров:

- окружение процесса — с нуля: `PATH`, свои `HOME`/`TMPDIR` на запуск,
  локаль; из окружения сервиса передаётся только `SKILLSPECTOR_OSV_TIMEOUT`;
- находки нормализуются: severity `critical/high/medium/low/info` (Cisco
  `SAFE` → `info`, незнакомое → `medium`), путь — относительно папки
  навыка, тексты движков — как есть (по-английски), фрагмент кода ≤ 500
  символов; ≤ 500 находок на запуск, отчёт движка ≤ 20 МиБ; подавленные
  эвристикой SkillSpector находки не берутся;
- SkillSpector все YARA-находки отдаёт с id `YR1` — адаптер достаёт имя
  правила из `pattern`, чтобы у обоих движков было `YARA_<имя>`;
- без доступа к OSV.dev SkillSpector берёт встроенные данные и оценивает
  зависимости строже — в отчёте предупреждение на весь скан.

`Engine.run(skill_dir, workdir, timeout, llm=None)` — место под LLM-режим:
с `llm` сейчас отказ.

## Свои правила и проверка frontmatter

**YARA-правила** — `scanner/skills/rules/yara/*.yara`, только на пробелы
движков, найденные на корпусе: закрепление через shell rc (`>>`/`tee -a` в
`~/.bashrc` и т.п.), через cron/launchd, `` !`…` `` с сетью, секретами или
base64. Имена — `skills_*`, в отчёте `rule_id` = `YARA_skills_*`.
`rules/build_pack.py` (только stdlib) при сборке образа проверяет `meta`
(категория из `ThreatCategory` Cisco, severity, описание, уникальность имён),
генерирует пак Cisco `rules/cisco-pack/` (`pack.yaml` schema v2 + копия
правил; в git не хранится) и компилирует правила и YARA-X (Cisco), и
libyara (SkillSpector) — сломанное правило валит сборку образа, а не скан.

Почему пак, а не `--custom-rules`: у Cisco `--custom-rules` **заменяет**
встроенные YARA-правила. Cisco прогоняет YARA только по телу `SKILL.md`
без frontmatter, поэтому правил на frontmatter в YARA нет.

**Проверка frontmatter** (`app/manifest_check.py`, движок `manifest`,
выполняется всегда, в процессе сервиса, тексты по-русски):

- `hooks` с командами (`type: command` или без типа, любая вложенность) →
  high `MANIFEST_HOOKS_COMMAND`;
- `allowed-tools` с неограниченным `Bash` (`Bash`, `Bash(*)`) → medium
  `MANIFEST_ALLOWED_TOOLS_BASH`; `Bash(git status:*)` не отмечается;
- каждый `` !`…` `` в теле (команда выполняется при загрузке навыка) → high
  `MANIFEST_SHELL_INJECTION`, не больше 20 на файл.

YAML читается безопасным загрузчиком; битый или слишком большой
frontmatter — предупреждение, а не находка.

## Вердикт

По каждому навыку (D-52), по находкам движков, которые отработали:

- **`block`** — находка high или critical от сигналов платформы (свои
  YARA-правила `YARA_skills_*` в любом движке или проверка frontmatter)
  **или** critical одновременно у Cisco и у SkillSpector (упавший или не
  выбранный движок не подтверждает);
- **`review`** — любая другая находка high/critical;
- **`pass`** — иначе. Это «находок high и выше нет», а не «безопасен»:
  medium/low/info видны в отчёте.

Общий вердикт — худший из навыков; отказ архива — `block`. У навыка
`verdict_reasons` — почему он получил вердикт. `confidence` в вердикте не
участвует; находки двух движков не склеиваются.

Почему так: на легитимных навыках оба движка регулярно дают high
(скрипты, сетевые запросы), и правило «critical → block» блокировало бы
нормальные навыки. На корпусе: из 19 легитимных навыков Anthropic `block`
не получил ни один, из 25 вредоносных `block` — 6, `review` — 16, `pass` — 3
(CVE-фикстуры Cisco, без LLM не видны). Прогон `anthropics/skills` (20
навыков, ~6 мин): `review` 11, `pass` 9.

## Данные

`Scan.results` — формат в [`SKILLSS.md` §2.7](../SKILLSS.md) (там же пример
живого отчёта). Коротко:

- верх: `engine: "skills-scanner"`, `source` (zip: файл, sha256, размер;
  git: URL, ветка, коммит, без токена), `archive` (только zip), `verdict`,
  `complete`, `rejected` (`{reason: zip_slip|symlink|encrypted|limits,
  detail}` или `null`), `llm: {enabled: false}`, `summary` по severity,
  `verdict_counts`, `engines` (выбранные движки + `manifest`: версия,
  статус `ok/partial/failed/timeout`, время, сколько навыков не
  отработало), `warnings` (на весь скан: OSV.dev), `findings_truncated`;
- `skills[]`: `name`, `path`, `verdict`, `verdict_reasons`, `complete`,
  `summary`, `engines` (статус движка по навыку, его справочный вердикт,
  ошибка, предупреждения), `findings_omitted`, `findings[]` (`engine`,
  `rule_id`, `severity`, `confidence`, `category`, `file`, `line`, `title`,
  `finding`, `fix`, `snippet`).

В `Scan.results` не больше 2000 находок на скан — самые серьёзные; сводки и
вердикт считаются по всем. Ограничение нужно потому, что `GET /scans`
отдаёт `results` целиком. Сырые отчёты движков не сохраняются.

Страница скана — `web/src/components/SkillsScanResults.tsx`: вердикт с
пояснением, неполнота, отказ архива, сводки, движки, навыки (сначала
`block`, раскрыты `block` и неполные) с причинами вердикта и находками,
фильтр по severity.

## Что где в коде

| Файл | Что делает |
|---|---|
| `control-api/app/scanner_registry.py` | регистрация `agent_skills`: `asset_kinds=("skill",)`, `requirements={"code"}`, фазы |
| `control-api/app/api/scans.py` | снимок источника в `Scan.config.source` при создании скана |
| `control-api/app/api/skill_assets.py` | активы, загрузка zip, `GET /skill-assets/{id}/content` (+ `X-Archive-SHA256`) |
| `scanner/skills/app/main.py` | `GET /health`, `GET /schema` (поле `engines`), `POST /run/{id}` |
| `scanner/skills/app/runner.py` | очередь, фазы, дедлайн, ошибки, прерванные сканы |
| `scanner/skills/app/stages.py` | точки подключения этапов |
| `scanner/skills/app/sources.py`, `archive.py`, `repo.py`, `git_auth.py` | получение исходников, распаковка, клон, поиск навыков |
| `scanner/skills/app/analysis.py` | запуск движков по навыкам, журнал, предупреждения |
| `scanner/skills/app/engines/` | `base.py` (находка, запуск, нормализация), `cisco.py`, `skillspector.py` |
| `scanner/skills/app/manifest_check.py` | проверка frontmatter |
| `scanner/skills/app/report.py` | вердикт и `Scan.results` |
| `scanner/skills/app/procs.py` | подпроцесс с таймаутом и убийством группы |
| `scanner/skills/rules/` | YARA-правила и `build_pack.py` |
| `scanner/skills/eval/` | корпус и сравнение движков |
| `web/src/components/SkillsScanResults.tsx` | отчёт на странице скана |

## Окружение

Сервис `scanner-skills` в `docker-compose.yml`: только default-сеть, без
опубликованного порта; hardening — `init`, `cap_drop: [ALL]`,
`no-new-privileges`, `mem_limit: 3g`, `cpus: 2`, `pids_limit: 256`.
Отдельного пользователя и read-only FS нет. kind, launcher и ключи LLM не
нужны; сеть нужна только SkillSpector для OSV.dev (без неё скан работает,
но с предупреждением).

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `CONTROL_API_URL` | `http://control-api:8000` | control-api |
| `SCAN_MAX_CONCURRENT` | 2 | сканов одновременно |
| `SCAN_ENGINE_TIMEOUT` | 300 | секунд на запуск движка по навыку |
| `SCAN_TOTAL_TIMEOUT` | 1800 | секунд на скан (без очереди) |
| `SCAN_MAX_SKILLS` | 50 | навыков на скан |
| `CISCO_BIN`, `SKILLSPECTOR_BIN` | пути в `/opt/engines/*` | CLI движков |
| `SKILLS_RULES_DIR` | `/srv/rules` в образе | свои правила и пак Cisco |
| `SKILLSPECTOR_OSV_TIMEOUT` | — | таймаут запросов SkillSpector к OSV.dev |

Образ (`scanner/skills/Dockerfile`): `python:3.12-slim` по digest, проверен на
arm64 (lock-файлы универсальные, годятся и для amd64). Три venv — сервис `/opt/service` и два движка — ставятся из
lock-файлов с хэшами (`requirements-*.lock`, генерирует
`scripts/compile-locks.sh`) с `--require-hashes --only-binary=:all:`.
SkillSpector нет на PyPI: его зависимости — из lock, сам пакет —
`git clone --branch v2.11.2` с проверкой SHA коммита.

## Тесты и корпус

Для этого модуля — явное исключение из правила «автотестов нет»
(см. `AGENTS.md`): pytest для `scanner/skills/**` и для логики
skill-активов в `control-api/tests/`. Зависимости pytest — только dev
(`requirements-dev.txt`), в образы не попадают. LLM не участвует; вместо
control-api — HTTP-сервер в памяти, вместо движков — их настоящие отчёты
(`tests/fixtures/engines/`) и подставные CLI; настоящие движки — в тестах
с меткой `docker` на собранном образе.

```bash
cd scanner/skills
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
docker compose build scanner-skills       # для тестов с меткой docker (иначе skip)
.venv/bin/python -m pytest                # -m "not docker" — без образа

cd control-api
python3 -m venv .venv && .venv/bin/pip install fastapi "uvicorn[standard]" sqlmodel httpx pyyaml alembic python-multipart -r requirements-dev.txt
.venv/bin/python -m pytest
```

Корпус `scanner/skills/eval/` — синтетические вредоносные навыки (домены
`*.invalid`, инертные маркеры), фикстуры из тестов самих движков и
легитимные навыки Anthropic; `run_eval.py` сравнивает движки и сверяет с
`baseline.json`. Как запускать — `scanner/skills/eval/README.md`.

**Обновление движка или правила:** новая версия → lock-файлы
(`scripts/compile-locks.sh`) → прогон корпуса в образе с сетью → сравнение
с `baseline.json` → осознанный `--update-baseline` → живой скан.

## Безопасность и ограничения

- **Без LLM.** Чисто текстовые атаки (инъекции в инструкциях без кода и
  явных маркеров) не ловятся; в отчёте — «Семантический (LLM) анализ не
  выполнялся». Место под LLM-режим оставлено (`llm`, `eval_llm_model_id`).
- **`pass` не значит «безопасен»** — значит, что находок high и выше нет.
- **Ложные срабатывания движков** на легитимных навыках со скриптами —
  поэтому большинство таких навыков получает `review`, а не `block`.
- **Файлы навыков не исполняются**, но разбираются чужими парсерами
  (движки, YAML, zip): защита — отдельные процессы, таймауты, лимиты
  распаковки и hardening контейнера, без отдельного пользователя и
  read-only FS.
- **Токен git** хранится в `Scan.config.source` в открытом виде и виден в
  `GET /scans` (принятый техдолг), в журнал и отчёт не попадает.
- **OSV.dev**: без сети severity зависимостей у SkillSpector выше.
- **Перезапуск сервиса посреди скана** — скан `failed`, нужно запустить
  заново.
