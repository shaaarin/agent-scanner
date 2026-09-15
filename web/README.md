# web — дашборд Agent Scanner

React + TypeScript + Vite. **Весь текст интерфейса — на русском.** Новый
текст добавляйте на русском и в том же тоне (см. `AGENTS.md`).

## Запуск

Обычно поднимается вместе со всем стеком:

```
docker compose up -d --build web
```

Интерфейс: http://localhost:4173 (сборка отдаётся статикой через `serve`).

Для разработки с HMR (нужен Node.js):

```
npm install
npm run dev
```

## Адреса API

Задаются на этапе сборки (build args `docker-compose.yml`):

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `VITE_CONTROL_API_URL` | `http://localhost:8000` | control-api (основные данные и API) |
| `VITE_LAUNCHER_URL` | `http://localhost:8400` | launcher (разбор репозитория в мастере конфигурации агента) |

Браузер обращается к ним напрямую; CORS на `control-api` открыт.

## Страницы

| Маршрут | Файл | Назначение |
|---|---|---|
| `/` | `pages/Dashboard.tsx` | плитки-переходы |
| `/scans`, `/scans/:id` | `pages/Scans.tsx`, `pages/ScansDetail.tsx` | создание сканирований и наблюдение за прогрессом |
| `/agent-configs` | `pages/AgentConfigs.tsx` | репозиторий, запуск и режим взаимодействия агента |
| `/llm-models` | `pages/LLMModels.tsx` | подключения к OpenAI-совместимым провайдерам |
| `/library` | `pages/Library.tsx` | библиотека знаний (локальные Markdown-материалы) |
| `/events` | `pages/Events.tsx` | перехваченный трафик; раскрытие тел запроса/ответа |

## Сборка и проверки

```
npm run build   # tsc -b && vite build
npm run lint    # oxlint
```

Автотестов нет — проверяйте живой сценарий через поднятый стек.
