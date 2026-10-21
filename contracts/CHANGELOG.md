# Changelog — contracts

Формат: [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/). Версия схемы — `schema_version` в ответах.

## [0.1.0] — 2026-10-21

### Added
- Первая версия моделей: `company_profile`, `news_item`, `event`, `ranked_events`,
  `business_insight`, `run_trace`, `claim` (с `claim_type` и `provenance`), `error`.
- Единая спецификация `openapi.yaml` с маршрутами API-шлюза.
- JSON-примеры в `examples/` для моков и контрактных тестов.

### Правила изменений
- Обратимые изменения (новое необязательное поле) — минорная версия.
- Удаление или переименование поля, смена типа — мажорная версия, требуется согласование всех владельцев.
