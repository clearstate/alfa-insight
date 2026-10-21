# Модель данных

Источник истины — [contracts/schemas](../contracts/schemas/). Здесь — связи и правила.

## Сущности

| Сущность | Ключ | Ссылки | Владелец записи |
|---|---|---|---|
| `CompanyProfile` | `company_id` | `links[].target_company_id` | profile |
| `NewsItem` | `item_id` | `dedup_group_id`, `companies[]` | ingestion |
| `Event` | `event_id` | `news_item_ids[]` | ingestion |
| `RankedEvent` | `event.event_id` + `rank` | `event` | ranking |
| `Claim` | `claim_id` | `provenance[].source_id` → `item_id` / `profile:<id>` | agent |
| `BusinessInsight` | `insight_id` | `company_id`, `event_id`, `claims[]` | agent |
| `RunTrace` | `run_id` | `company_id`, `event_id` | agent |
| `ErrorResponse` | `request_id` | — | api |

## Правила

- `Provenance.source_id` — внешний ключ, который можно разрешить обратно: `news_item.item_id`
  или `profile:<company_id>`. UI показывает фрагмент и ссылку.
- `Claim.provenance` пуст **только** для `recommendation` и `estimate`; для `fact` и `inference` — обязателен
  (проверяет критик и контрактный тест).
- `CompanyProfile.completeness` — доля заполненных обязательных признаков; `missing_fields` — какие именно.
- `Event` собирается из нескольких `NewsItem` (дедупликация); `severity` — нормализованная важность.
- `RunTrace` неизменяем: это журнал конкретного прогона, включая версии промптов и моделей.
- Все временные метки — ISO 8601 с таймзоной (UTC).
