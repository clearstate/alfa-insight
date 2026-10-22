# Запросы и передача: участники 1, 4, 5, 6 (от участника 2)

## Участник 1 (company_profile)
1. **Словарь `industry_terms.yaml` даёт ложные срабатывания основ слов** (мы лемматизацию не делаем — внешних моделей нет). Найдено на 9 документах банка:
   `shipping` ← «порт» в «портфель»; `telecom` ← «связи» в предлоге «в связи с»; `forestry_paper` ← «бумаг» в «ценные бумаги»; `finance` ← «банк»/«страхов»
   в любой макро-заметке. Я обхожу это в `config/industry_overrides.yaml` (вырезаю контексты перед поиском). Предложение: заменить основы на более узкие («портов», «порта», «морск порт»;
   «телеком», «связь» только в составе «услуги связи»; «бумага», «целлюлоз») и/или добавить `ambiguous_terms`.
2. В `docs/company_profile_contract.md` написано 38 тем, в `feature_rules.yaml` их **36**; `contracts/news_vocab.py::TOPICS_V1` = 36, тест `test_integration_company_profile` ловит рассинхрон. Подтвердите набор.
3. Ваш вопрос про `claim_type`: у меня `fact | bank_view | ai_inference | unknown` + поле `method: rule|llm|manual` у фактов — отдельное значение `rule_inference` не нужно.
4. Оставляю вам `okved_prefixes` как основной ключ; все префиксы проходят `validate_prefix` (тест).

## Участник 4 (поиск и ранжирование)
- **Проверено на реальных данных (115 крупных компаний):** пересечение тем без весов не различает компании (100+ из 115 на каждую новость). Используйте `Σ topic_scores[t] × profile.topics[t].weight` (разброс реальный), затем ОКВЭД (редкое точное совпадение — сильный сигнал), регион, страны. Совпадение по стране само по себе слабо (макро-обзор упоминает Китай — 35 компаний): засчитывать вместе с темами `foreign_trade`/`fx_rates`/`sanctions`.
- Строки `regions` и `countries` совпадают с `geography.region` и `foreign_trade.countries` профиля символ в символ (проверено по всем значениям CSV).
- Данные: `NewsStore.search_candidates(topics, okved_prefixes, regions, since, until, source_types, include_duplicates, limit)`; индексируемые таблицы `item_topics`, `item_industries`, `item_regions`; чанки `chunks` (для RAG, с `page`).
- Новые материалы: `GET /api/news/changes?since_id=` (поллинг; события created/updated/duplicate) — push не делаю.
- Дубли исключены из выдачи по умолчанию (`dup_of`); кластеры — `event_cluster_id` (показывать один материал на кластер, URL остальных — в `event_clusters`/`news_items`).
- `source_reliability.score` можно использовать в ранжировании; `stale_document` — понижать.
- Полнотекстовый поиск (`tsvector`) делаете вы: колонки `news_items.title`, `chunks.text`; миграцию согласуем с участником 6. Эмбеддинги не используются (нет в списке моделей).

## Участник 5 (интерфейс)
- Показывать `claim_type`: «позиция банка» (`bank_view`), «факт из источника» (`fact`), «вывод AI» (`ai_inference`, делает участник 3), «не подтверждено» (`unknown`).
- Для ссылки на первоисточник: `provenance.url` (новости) или `bank.source_file` + `page` (аналитика банка); чанки — `GET /api/news/{id}/chunks`.
- Статусы: `needs_review`, `stale_document`, `cluster_conflict` — показывать пометку.
- Режим «вставить новость»: `POST /api/news/ingest` ({url} или {text,title}); ответ: `outcome`, `item_id`, `status`, `reasons`.

## Участник 6 (интеграция)
- Схема БД `news_ingest` (14 таблиц), DDL: `services.news_ingest.store.render_ddl("postgres")`; `docker-compose.news_ingest.yml`, `Dockerfile.news_ingest` (**не собирались**), `requirements.news_ingest.lock.txt`, фрагмент `pyproject.news_ingest.fragment.toml` для слияния, `THIRD_PARTY_NOTICES.news_ingest.md`.
- Подключение к общему приложению: `errors.install(app); app.include_router(news_router); app.state.news_store/news_pipeline` (`services/news_ingest/main.py::build`).
- Ждём от вас: общий `uv.lock`; решение, хранить ли PDF-исходники в репозитории (сейчас в Git лежат только экстракты, PDF — нет); переменные окружения (`NEWS_DB_URL`, `NEWS_INGEST_*`, `LLM_*`).
- Проверить на стенде: API (fastapi/pydantic), PostgreSQL-ветку хранилища, Docker-сборку, OCR русского.
