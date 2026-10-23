# Корпус и сравнение движков (подзадача 1)

Здесь живёт корпус скиллов для модуля сканирования Agent Skills и скрипт, который
прогоняет его через оба движка (Cisco `skill-scanner` 2.1.0 и NVIDIA `SkillSpector` v2.11.2,
только статика, без LLM). Зачем: видеть, что реально ловит каждый движок, где у них
пробелы (их закрывают наши правила, подзадача 7), и ловить регрессии при смене версий.

## Состав корпуса

| Каталог | Что | Откуда |
|---|---|---|
| `corpus/cisco/`, `corpus/cisco-test/` | инертные фикстуры по категориям угроз с разметкой | тесты Cisco (Apache-2.0) |
| `corpus/skillspector/` | несколько фикстур | тесты SkillSpector (Apache-2.0) |
| `corpus/marker/` | 5 маркерных заглушек: `hooks`, закрепление в shell rc, `` !`cmd` `` (с `echo` и с `curl` на `*.invalid`), чистый скилл | наши, инертные: `echo` или домен `.invalid` |
| `.external/anthropics-skills/` | 19 легитимных скиллов (негативные примеры) | `fetch_external.sh`, не в git |

Атак-наборов мы не генерируем: вредоносные примеры берутся из тестовых наборов самих
движков, а для известных пробелов у нас по одной минимальной заглушке. Источники и
лицензии: `NOTICE.md`.

## Запуск

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
./fetch_external.sh                      # легитимные навыки Anthropic (необязательно)
export CISCO_BIN=/путь/к/skill-scanner SKILLSPECTOR_BIN=/путь/к/skillspector
.venv/bin/python run_eval.py --with-external      # таблица -> results/report.md
.venv/bin/python run_eval.py --update-baseline    # после осознанной смены версий движков
.venv/bin/python -m pytest                        # тесты (FULL_EVAL=1 добавляет полный прогон ~3 мин)
```

Эталонная среда — образ `scanner-skills` (те же версии и lock-файлы, что в продукте):

```bash
docker compose build scanner-skills
docker run --rm -v "$PWD:/eval" -w /eval --entrypoint sh agent-scanner-scanner-skills \
  -c 'python run_eval.py --cisco-bin $CISCO_BIN --skillspector-bin $SKILLSPECTOR_BIN'
```

Severity SkillSpector по зависимостям зависит от доступности OSV.dev: без сети он берёт
встроенные данные и оценивает строже. Поэтому эталон — образ **с сетью**, `baseline.json`
снят так (R-32, D-50 в `SKILLSS.md`); прогон без сети разойдётся с ним в кейсе
`cisco/supply-chain-attack/unpinned-dependency`.

Прогон идёт **со своими правилами**, как в продукте: в образе они берутся из
`$SKILLS_RULES_DIR` (`/srv/rules`, пак Cisco собран при сборке), вне образа —
`--rules-dir` с собранным `rules/build_pack.py --out rules/cisco-pack`. Без правил скрипт
предупреждает: результат не сравним с baseline.

`manifest.yaml` генерируется `build_manifest.py` (метки Cisco берутся из их `_expected.json`).
Новый каталог в `corpus/` без записи в `EXPLICIT` генератор не пропустит. `baseline.json`
хранит максимальную severity по каждому кейсу и движку; движки запинены, поэтому любой
сдвиг при смене версии виден.

## Результаты (Cisco 2.1.0 + SkillSpector v2.11.2 + свои правила, порог «поймал» = HIGH и выше)

На 25 вредоносных и 26 безвредных (7 из корпуса + 19 anthropics/skills @ dbd4588), 2026-10-15:

| Движок | Поймал вредоносных | Ложные на безвредных |
|---|---|---|
| Cisco | 20/25 (без своих правил — 18/24) | 5/26 |
| SkillSpector | 8/25 (без своих правил — 7/24) | 10/26 |
| Объединение | 20/25 | — |
| + проверка frontmatter сервиса (`app/manifest_check.py`) | 22/25 | 0/26 |

Проверка frontmatter не входит в этот скрипт (это код сервиса, не движок); последняя строка —
по её тестам на тех же кейсах: она добавляет `marker/hooks-command` и `marker/bang-injection`.

Выводы, которые влияют на архитектуру:

1. **Cisco сильнее на коде** (шаблоны, taint, поведенческий анализ), **SkillSpector** ловит
   часть YARA-сигнатур (закрепление в системе), но на корпусе Cisco заметно слабее.
   Оба нужны (D-02), но объединение даёт всего +1 к Cisco: ценность второго движка надо
   смотреть и на реальных скиллах, а не только на этом корпусе.
2. **Пробелы движков и как закрыты (подзадача 7, D-51):** закрепление в shell rc Cisco не
   ловил — теперь ловит своим YARA-правилом; `` !`cmd` `` с сетью/секретами — YARA-правило в
   обоих движках; `hooks` с командой и любой `` !`cmd` `` — проверка frontmatter сервиса
   (Cisco frontmatter не видит, поэтому YARA тут не помогает). Свои правила не дали ни одного
   нового срабатывания на 19 легитимных скиллах.
3. **Ложные срабатывания на легитимных скиллах высокие.** Cisco ставит CRITICAL на
   `claude-api`, `docx`, `skill-creator` (`os.system`, цепочки чтения env), SkillSpector
   даёт HIGH на 10 из 19 (в основном «Anti-Refusal Statement», «Env Variable Harvesting»,
   «Hidden Instructions»). Правило из D-12 «critical → block» без доработки будет
   блокировать нормальные скиллы. Нужно решение: например, block только при совпадении
   или при критичных категориях, остальное в review.
4. Три CVE-подобные фикстуры Cisco (`flowise`, `mcp-atlassian`, `mcpwn`) пропускают оба
   движка в статике; Cisco, возможно, ловит их только в LLM-режиме.
