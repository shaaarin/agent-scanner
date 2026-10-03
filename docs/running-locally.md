# Локальный запуск

## Что понадобится

- Docker и Docker Compose.
- Для сканирований — кластер Kubernetes. Локально используется `kind`
  (см. [раздел 4](#4-кластер-kubernetes-kind)).
- Реальный OpenAI-совместимый LLM-провайдер. Моков в платформе нет: и
  перехватываемый агент, и модель-судья DeepTeam ходят в настоящий
  провайдер. Результаты недетерминированы — это честный результат теста.
- Для анализа кода — ключ Promptfoo (`PROMPTFOO_API_KEY`). Кластер для
  анализа кода не нужен.

## 1. Переменные окружения

```
cp .env.example .env
```

Заполните `LLM_PROVIDER_BASE_URL` / `LLM_PROVIDER_API_KEY` /
`LLM_PROVIDER_MODEL`. Значения понадобятся, чтобы зарегистрировать
`LLMModel` в UI (раздел 5). Подойдёт любой OpenAI-совместимый endpoint:
OpenAI, OpenRouter, self-hosted vLLM/Ollama и т.п.

Для анализа кода заполните `PROMPTFOO_API_KEY` — его docker compose
передаёт сервису `scanner-promptfoo`. Анализ выполняет облако Promptfoo:
код проверяемого агента уходит к ним. Для своего сервера Promptfoo
(Enterprise On-Prem) задайте `PROMPTFOO_CODE_SCAN_API_HOST`. После
изменения ключа пересоздайте сервис: `docker compose up -d scanner-promptfoo`.

## 2. Запуск стека

```
docker compose up -d --build
```

Поднимаются:

| Сервис | Адрес |
|---|---|
| `control-api` | http://localhost:8000 |
| `web` | http://localhost:4173 |
| `proxy` | http://localhost:8100 |
| `launcher` | http://localhost:8400 |

Сканеры `scanner-deepteam` и `scanner-promptfoo` работают без опубликованного
порта — `control-api` обращается к ним по внутренней сети. Проверка:
`curl localhost:8000/health`.

> Если стек поднимался до разделения сканеров, удалите старый контейнер
> `scanner`: `docker compose up -d --build --remove-orphans`.

Только анализ кода, без кластера (сеть `kind` не нужна):

```
docker compose up -d --build control-api web scanner-promptfoo
```

## 3. Включение `launcher` и `scanner-deepteam`

`launcher` и `scanner-deepteam` работают с Kubernetes-кластером по kubeconfig
`.kube-kind-config.yaml` (bind-mount). Если файла нет — `launcher` не
сможет ничего запустить, а сканирование упадёт на фазе «Запуск агента».

>`pod_manager.py` ссылается на **фиксированный тег**
> `kind-registry:5000/agent-scanner-proxy:latest`. Пересобирайте и пушьте
> образ в локальный реестр перед запуском агента **и после каждого изменения
> в `proxy/`** — иначе сайдкар Pod'а продолжит ходить через старый образ, и
> правки (например, подстановка `x-opencode-session`) не применятся.

```
docker compose build proxy
docker tag agent-scanner-proxy:latest localhost:5001/agent-scanner-proxy:latest
docker push localhost:5001/agent-scanner-proxy:latest
```

## 4. Кластер Kubernetes (`kind`)

Разовая настройка локального `kind`-кластера с локальным реестром:

```
# 1. kubectl и kind (пропустите, если уже есть; кладите в ~/bin)
curl -sLo ~/bin/kubectl "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64" && chmod +x ~/bin/kubectl
curl -sLo ~/bin/kind "https://kind.sigs.k8s.io/dl/v0.24.0/kind-linux-amd64" && chmod +x ~/bin/kind

# 2. Локальный реестр, привязанный к (ещё не созданной) сети kind
docker run -d --restart=always -p "127.0.0.1:5001:5000" --name kind-registry registry:2

# 3. Кластер kind, настроенный доверять этому реестру
cat <<'EOF' > /tmp/kind-config.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
containerdConfigPatches:
  - |-
    [plugins."io.containerd.grpc.v1.cri".registry.mirrors."kind-registry:5000"]
      endpoint = ["http://kind-registry:5000"]
nodes:
  - role: control-plane
EOF
~/bin/kind create cluster --name agent-scanner --config /tmp/kind-config.yaml
docker network connect kind kind-registry
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: local-registry-hosting
  namespace: kube-public
data:
  localRegistryHosting.v1: |
    host: "localhost:5001"
    help: "https://kind.sigs.k8s.io/docs/user/local-registry/"
EOF

# 4. Kubeconfig для launcher/scanner-deepteam — внутренний адрес (они в сети kind),
#    не host-mapped
export PATH="$HOME/bin:$PATH"
kind get kubeconfig --name agent-scanner --internal > .kube-kind-config.yaml
```

Пересобирать кластер заново (`kind create cluster`) нужно после перезапуска
Docker Desktop: контейнер реестра переживает перезапуск (`--restart=always`),
а сам кластер — нет. После пересоздания повторите шаг 4.

## 5. Регистрация LLM-модели

Модель-судья (симулятор атак и оценка) — отдельный `LLMModel`. Через UI:
**LLM-модели → Добавить модель**. Или через API:

```
source .env
curl -s -X POST localhost:8000/llm-models -H "Content-Type: application/json" \
  -d "{\"name\":\"judge\",\"provider_type\":\"openai\",\"base_url\":\"$LLM_PROVIDER_BASE_URL\",\"api_key\":\"$LLM_PROVIDER_API_KEY\",\"model\":\"$LLM_PROVIDER_MODEL\"}"
```

`api_key` у списка маскируется; при редактировании пустое поле означает
«не менять».

## 6. Конфигурация агента

**Конфигурации агентов → Новая конфигурация.** Мастер: шаг 1 — репозиторий,
шаг 2 — настройка.

- **Репозиторий (git URL)** и ветка. Для приватных HTTPS-репозиториев —
  токен доступа.
- **Dockerfile** — путь к Dockerfile в репозитории (контекст сборки —
  всегда корень репо).
- **`.env.example`** — если указан, платформа дозаполнит переменные
  окружения значениями из репозитория.
- **Переменные окружения** — в том числе **реальные ключи и адрес LLM
  тестируемого агента**: платформа их не подставляет, агент должен уметь
  работать сам. Перехват произойдёт поверх.
- **Порт API** — если агент слушает HTTP (например, LangGraph — `8123`),
  укажите порт: `launcher` сам создаст `NodePort` и пропишет адрес.
- **Режим взаимодействия** — `REST API` или `LangGraph` (нужен, чтобы
  платформа могла вести диалог с агентом; `Без диалога` — скан не сможет
  обратиться к агенту).

### Режим REST API

Подходит для любого HTTP API агента. Сообщение атаки подставляется в
плейсхолдеры:

- `{{message}}` — текст атаки;
- `{{session_id}}` — новый UUID на каждый разговор (для API, которым нужен
  id диалога или сессии).

Плейсхолдеры работают в пути и параметрах URL (подставляются
URL-кодированными), в заголовках и в теле.

| Поле | Что задаёт |
|---|---|
| URL | Путь эндпоинта, например `/chat` или `/ask?q={{message}}`. Хост и порт при заданном «Порте API» платформа подставит сама. |
| Метод | `POST`, `GET`, `PUT`, `PATCH`. |
| Формат тела | `JSON` (плейсхолдеры внутри строк, экранирование автоматическое), `Форма` (x-www-form-urlencoded, шаблон — JSON-объект), `Текст` (произвольная строка). Для `GET` поля шаблона уходят в параметры URL. |
| Заголовки | Например `Authorization: Bearer ...` или `X-Session-Id: {{session_id}}`. |
| Поле ответа | Путь к ответу агента в JSON: `reply`, `data.0.text`, `messages.-1.content` (−1 — последний элемент). Пусто — весь ответ как текст. Если поля в ответе нет, кейс считается ошибкой. |
| Путь проверки готовности | Куда стучаться, пока агент стартует. Пусто — как раньше: путь эндпоинта без `/chat` + `/ok`; если в пути есть плейсхолдер — `/`. Готов — любой ответ с кодом ниже 500. |

Под формой — пример запроса с подставленным сообщением: по нему видно,
что именно уйдёт агенту.

Пример: LangGraph-агент через его stateless API — URL `/runs/wait`, метод
`POST`, тело
`{"assistant_id": "agent", "input": {"messages": [{"role": "user", "content": "{{message}}"}]}}`,
поле ответа `messages.-1.content`, путь проверки `/ok`.

## 7. Сканирование

**Сканирования → Новое сканирование**: имя, тип «Динамическое
тестирование», тестируемый агент, LLM-модель для оценки, набор уязвимостей
и атак.

Затем на странице скана — **Запустить сканирование**. Откроется детальная
страница с фазами и живым журналом:

```
Инициализация → Запуск агента → Ожидание агента → Тестирование →
Сохранение результатов → Завершено
```

Сборка агента через Kaniko занимает несколько минут. По завершении — блок
результатов: доля пройденных проверок и разбивка по уязвимостям (статус
«Устойчив»/«Уязвим», риск, обоснование модели-судьи).

### Анализ кода

**Сканирования → Новое сканирование**, тип «Анализ кода (promptfoo)»:
имя, агент (берутся его репозиторий, ветка и токен), минимальная
серьёзность и, при желании, дополнительные инструкции сканеру. LLM-модель
не нужна, кластер тоже.

```
Инициализация → Клонирование → Анализ кода → Сохранение результатов →
Завершено
```

Анализ обычно идёт 3–20 минут; пока он идёт, в журнал раз в 30 секунд
пишется, сколько прошло времени. Результат — счётчики по серьёзности,
общий вывод сканера и таблица находок; по клику на находку — рекомендация
и готовый промпт для AI-ассистента.

Через API:

```
curl -s -X POST localhost:8000/scans -H "Content-Type: application/json" \
  -d '{"name":"code","type":"code_scan","agent_config_id":1,"status":"pending","session_id":"scan-code-1","config":"{\"min_severity\":\"medium\"}"}'
curl -s -X POST localhost:8000/scans/<id>/start
curl -s "localhost:8000/scans/<id>/logs"
```

## 8. События

**События** — перехваченный трафик агента к LLM. Строки обновляются
автоматически; нажмите на строку, чтобы открыть тела запроса и ответа
(парные события одного `flow_id` показываются вместе). Фильтр — по
`session_id`.

## 9. Библиотека знаний

Материалы лежат в `library/<категория>/*.md` и подхватываются без
пересборки. Формат файла:

```md
---
title: "Заголовок"
summary: "Одно предложение для карточки."
tags: [prompt-injection, owasp]
source: "OWASP"          # необязательно
date: 2026-09-15         # необязательно, иначе дата файла
category: agents         # необязательно, иначе имя папки
---
# Тело материала (Markdown, поддерживаются таблицы)
```

## 10. Миграции базы

`control-api` применяет Alembic на старте. После изменения
`control-api/app/models.py`:

```
docker compose exec control-api alembic revision -m "краткое описание"
# отредактируйте upgrade()/downgrade() в новом файле версии
docker compose restart control-api     # применит миграцию
```

Тома не удаляются — данные сохраняются. Ревизии пишутся в
`control-api/app/migrations/versions/` (папка смонтирована на хост).

## 11. Диагностика

- **`launcher`/`scanner-deepteam` не видят кластер.** Проверьте, что
  `.kube-kind-config.yaml` существует и свежий (адрес меняется при
  пересоздании кластера): `kubectl --context kind-agent-scanner get nodes`.
- **Под агента не поднимается.** `kubectl get pods -n scan-<slug(session_id)>`
  и `kubectl logs ... -c agent`. Образ агента тянется из локального
  реестра — убедитесь, что он собран и доступен кластеру. Namespace такого
  скана остаётся для диагностики; после разбора удалите его
  (`kubectl delete ns scan-...`). Если агент успел ответить, namespace
  удаляется автоматически в конце скана.
- **Скан упал на «Ожидание агента» с сообщением про reachable-адрес.**
  В конфигурации агента не указан `Порт API` — платформе некуда
  обращаться.
- **Плавающий опубликованный порт** (`ERR_EMPTY_RESPONSE`, connection
  reset) на WSL2/Docker Desktop. Это quirk dev-окружения: для
  `control-api`/`launcher` опубликованный порт владеет `socat`-мост, а не
  сам сервис. Если проблема всё же появилась — обращайтесь к сервису
  изнутри сети: `docker compose exec control-api python3 -c "import httpx; print(httpx.get('http://localhost:8000/health').text)"`.
- **`can't pull image` при запуске агента.** Образ прокси нужно положить в
  локальный реестр (раздел 3).
- **Провайдер отвечает `MissingSessionID` / `x-opencode-session`.** Значит,
  сайдкар Pod'а работает со старым образом прокси. Пересоберите и запушьте
  образ в локальный реестр (раздел 3) и запустите агента заново.
- **Анализ кода падает на «Инициализация» с `PROMPTFOO_API_KEY`.** Ключ не
  задан: заполните его в `.env` и пересоздайте
  `docker compose up -d scanner-promptfoo`.
- **Анализ кода падает на «Клонирование».** Неверный адрес, ветка или
  токен репозитория в конфигурации агента. Токен в журнал не пишется.
- **«Сканер пока не подключён» при запуске.** Тип скана без своего сервиса
  (`mcp`, `agent_skills`) — так и задумано.
- **`403 namespace is being terminated` при `/launch`.** Ретест сразу после
  `/stop`: namespace ещё удаляется. Дождитесь, пока
  `kubectl get ns` перестанет показывать `scan-*`, и повторите запуск.
