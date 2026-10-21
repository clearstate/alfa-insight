# Third-party notices

Перечень сторонних компонентов, моделей, данных и смоделированных интеграций проекта.
Перед финальной сдачей замените версии-плейсхолдеры `TODO` на фактические (лицензия обязательна).

## Библиотеки

### Python

| Компонент | Назначение | Лицензия | Статус |
|---|---|---|---|
| FastAPI | HTTP-фреймворк сервисов | MIT | TODO: версия |
| Uvicorn | ASGI-сервер | BSD-3-Clause | TODO: версия |
| Pydantic / pydantic-settings | модели и настройки | MIT | TODO: версия |
| pytest, httpx | тесты | MIT / BSD-3-Clause | TODO: версия |
| ruff, mypy | линт и типы | MIT | TODO: версия |
| openapi-spec-validator | проверка контракта | Apache-2.0 | TODO: версия |

### Frontend

| Компонент | Назначение | Лицензия | Статус |
|---|---|---|---|
| React, React DOM | UI | MIT | TODO: версия |
| React Router | маршрутизация | MIT | TODO: версия |
| Vite, TypeScript | сборка | MIT / Apache-2.0 | TODO: версия |
| MSW | моки API (TEMP) | MIT | TODO: версия |
| openapi-typescript | типы из OpenAPI | MIT | TODO: версия |
| Playwright | e2e-тесты | Apache-2.0 | TODO: версия |

### Инфраструктура

| Компонент | Лицензия |
|---|---|
| PostgreSQL | PostgreSQL License |
| Redis | BSD-3-Clause (версии ≤ 7.2) |
| Nginx | BSD-2-Clause |

## Модели

| Роль | Модель | Лицензия / условия | Где используется |
|---|---|---|---|
| Планировщик | TODO | TODO | `services/agent/config/models.yaml` → `plan` |
| Синтез / follow-up | TODO | TODO | `… → synth`, `followup` |
| Самопроверка | TODO | TODO | `… → critic` |
| Эмбеддинги | TODO | TODO | `services/ranking/` |

Указать: провайдера (API), условия использования, ограничения на персональные данные, стоимость на токен.

## Датасеты

| Датасет | Источник | Лицензия | Где |
|---|---|---|---|
| Данные кейса (CSV, PDF) | TODO: ссылка | определить, размещать ли в репозитории | `data/raw/` (не коммитится) |
| Синтетические данные | сгенерированы командой | TODO | `data/synthetic/` |
| Оффлайн-разметка | руками команды | TODO | `data/eval/` |

## Шрифты и иконки

| Ресурс | Лицензия | Где |
|---|---|---|
| TODO (например, Inter) | SIL OFL 1.1 | `frontend/src/styles/` |
| TODO (набор иконок) | TODO | `frontend/src/components/` |

## Смоделированные интеграции

| Интеграция | Что смоделировано | Как отличить в UI/API |
|---|---|---|
| Источники новостей | TODO | `source_type` / бейдж источника |
| PDF аналитики | TODO | `source_type: analytics_pdf` |
| Внешний LLM | заглушка `LLM_PROVIDER=stub` в тестах | `model_versions` в трассе |
| Аутентификация | демо-пользователи | TODO |
