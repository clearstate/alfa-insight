# Контракт `news_item/1.0` (владелец — участник 6; поставщик — участник 2)

Исходник: `contracts/news_item.py` (Pydantic v2), словари — `contracts/news_vocab.py`. Пример данных: `data/export/items.jsonl`.

## Главные поля
| Поле | Смысл |
|---|---|
| `id` | `news_` + SHA-256(url_key)[:20]; стабилен при повторном импорте |
| `title`, `text`, `summary`, `url`, `canonical_url`, `publisher`, `language` | содержимое и происхождение |
| `published_at` | ISO 8601 UTC; `null` если дату не нашли (тогда `processing_status=needs_review`); `date_precision`: `day`/`second` |
| `event_date` | дата события (может отличаться от публикации; у банка — из метаданных) |
| `topics`, `topic_scores` | **словарь v1 участника 1** (36 тем) — напрямую пересекаются с `profile.topics[].topic` |
| `industries.okved_prefixes` | **основной ключ** для `match_company()` / `match_supply_chain()`; `okved_sections` — только грубый фильтр |
| `regions`, `countries`, `entities` | **те же строки, что в профиле:** `regions` = официальные названия из `REGION` (`Москва`, `Республика Татарстан`; «Дальний Восток», «Сибирь», «Урал», «Юг России», «Поволжье» разворачиваются в список регионов), `countries` = как в `FTS_COUNTRY_NAME` (`КИТАЙ`, `ЮЖНАЯ КОРЕЯ`). Упоминание страны в макро-обзоре — не торговая связь |
| `key_facts[]` | `{text, claim_type, method, span{start,end,page}, topics, provenance}` |
| `bank_views[]` | позиции банка: `kind` = forecast / assessment / recommendation, `page`, `topics`, `provenance` |
| `numeric_claims[]` | числа: `key_rate_pct`, `inflation_yoy_pct`, `usd_rub` |
| `event_cluster_id`, `dup_of` | кластер события; ссылка на оригинал, если это дубль |
| `source_reliability` | `{score 0..1, rule}`; устаревшие документы — 0.2 |
| `processing_status`, `status_reasons`, `security_flags` | `ok / needs_review / failed / duplicate`; причины; подозрения на инъекцию |
| `provenance`, `extraction` | источник, SHA-256 сырья, метод извлечения (`html`, `pdf_vision_sidecar`, `pdf_text`, `pdf_ocr`, …) |
| `bank` | для аналитики банка: `author_unit`, `doc_family`, `stale`, `source_file`, `published_at_note`… |
| `version` | растёт при изменении текста по тому же URL |

## claim_type (сквозное требование)
`fact` — утверждение из текста; `bank_view` — прогноз/оценка/рекомендация банка (правило по маркерам); `ai_inference` — вывод модели (**модуль 2 такие не создаёт; создаёт участник 3**);
`unknown` — оговорка/слух/неподтверждённое (для новостей). Факты, извлечённые LLM, имеют `method="llm"` и проходят проверку заземления (дословная цитата).

## Чанки и показатели
- `GET /api/news/{id}/chunks`: чанки ≤ ~900 символов с `page` (для цитирования первоисточника), `topics`, `claim_type` (`bank_view`, если в чанке есть маркеры позиции банка).
- `macro_indicators` / `GET /api/indicators`: `indicator` (канонический ключ: `key_rate_eoy`, `key_rate_avg`, `key_rate_path`, `inflation_dec_yoy`, `usd_rub_eoy`, `gdp_growth`, `unemployment`, `wages_nominal`, `retail_turnover`, … или `other:<slug>`), `period` (`2026`, `2026-07`, `2026-H1`, `2026-Q1`), `is_forecast`, `page`.
- `forecasts_latest.json`: действующее значение прогноза + список заменённых (**брать прогнозы банка отсюда**).

## Версионирование
Любое изменение контракта — PR в `contracts/` с описанием, ревью участников 3, 4, 6 и `schema_version`++.
Отличия от исходного ТЗ: темы — словарь участника 1 вместо списка из ТЗ (`contracts/news_vocab.py::LEGACY_TOPIC_MAP`, в ТЗ было 14 тем, у участника 1 — 36);
добавлены `date_precision`, `countries`, `bank_views`, `numeric_claims`, `topic_scores`, `security_flags`, `status_reasons`.
