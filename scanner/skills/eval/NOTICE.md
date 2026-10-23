# Источники фикстур

Фикстуры в `corpus/` взяты из тестовых наборов самих движков (оба под Apache-2.0) и
используются как инертные примеры для проверки сканера. Оригинальные заголовки лицензии
в файлах сохранены.

| Каталог | Источник | Лицензия |
|---|---|---|
| `corpus/cisco/`, `corpus/cisco-test/` | cisco-ai-defense/skill-scanner, `evals/skills`, `evals/test_skills` (коммит a24df34) | Apache-2.0, © Cisco Systems, Inc. |
| `corpus/skillspector/` | NVIDIA/skillspector, `tests/fixtures` (коммит 2226747) | Apache-2.0, © NVIDIA |
| `corpus/marker/` | собственные маркерные фикстуры; выполняют только `echo` | как весь репозиторий |

Из набора Cisco исключён `eicar-test` (содержит антивирусную тестовую строку: антивирусы
на рабочих машинах помечают такие файлы и могут удалить их из репозитория).

Легитимные навыки `anthropics/skills` в репозиторий **не копируются**: часть из них
(docx, pdf, pptx, xlsx) распространяется на условиях source-available. Они подтягиваются
скриптом `fetch_external.sh` на зафиксированный коммит в `.external/` (каталог в .gitignore).
