# Changelog

## news_ingest 0.1.0 — участник 2
- Модуль `services/news_ingest`: конвейер новостей и аналитики банка -> `news_item/1.0` (`contracts/news_item.py`, `contracts/news_vocab.py`).
- Первая вертикаль: 9 документов банка (транскрипции страниц `data/bank_analytics/*.extract.json`) -> 9 элементов, 164 чанка, 492 показателя; повторный запуск идемпотентен.
- Дедупликация (SHA-256, MinHash), версии, кластеры событий и пометка противоречий; безопасная загрузка (SSRF, robots, ретраи); RSS/HTML/PDF; LLM-слой с кешем, бюджетом и заземлением.
- Парсер макротаблиц банка и разрешение расхождений прогнозов между документами (`data/export/forecasts_latest.json`).
- Проверка на реальном датасете: география из данных (`scripts/build_news_geo.py`), 115 крупных компаний, сквозные тесты.
- 86 тестов (`python scripts/run_news_tests.py`). Не проверено: pydantic/fastapi-слой, PostgreSQL, Docker, OCR русского, внешние источники.

# CHANGELOG — company_profile (участник 1)

## 0.3.0 — цепочка поставок (запрос: сохранить сводку, детализировать коды контрагентов, тесты на точное совпадение)

- **Сохранено без изменений:** `details.suppliers` и `details.customers` фактора `supply_chain_industries` (сводка по классам ОКВЭД).
- **Добавлено** в `details`:
  - `supplier_codes` и `customer_codes` — агрегаты по полному коду ОКВЭД контрагентов: `okved_code`, `okved_levels`, `pay_amt`, `pay_cnt`, `n_counterparties`, `share_of_known`. Id контрагентов в детализацию не входят. На направление выводится до `top_codes = 50` кодов.
  - `supplier_codes_meta` и `customer_codes_meta`: `n_codes`, `truncated`, `omitted_share_of_known`.
  - `rule_shares` — доля известного оборота по каждому отраслевому правилу.
  - Модели контракта: `SupplyChainDetails`, `SupplyChainCode`, `SupplyChainCodesMeta`, `SupplyChainDivision`.
- **Добавлено:** `industry_terms.match_supply_chain(prefixes, profile)`. Совпадение — только равенство префикса одному из уровней кода. Некорректные префиксы вызывают `InvalidOkvedPrefix` (раньше молча игнорировались в `match_company`).
- **Исправлено:** темы цепочки поставок раньше сопоставлялись только по двузначному классу, поэтому правила с глубокими префиксами (`07.29.4`, `46.46`) на контрагентах не срабатывали. Теперь сопоставление идёт по уровням кода и по всем кодам, а не только по выведенным.
- **Исправлено:** `okved_levels` принимал некорректный формат `XX.X.X` (например `45.3.1`).
- Схема БД не изменилась (детализация хранится внутри JSONB профиля).

## 0.2.0

Хранилище:
- PostgreSQL как основное хранилище: схема `company_profile` (`services/company_profile/db.py`, DDL в `db_sql/schema.postgres.sql`).
- ETL `python -m services.company_profile.etl`. Перезагрузка выполняется в одной транзакции, каждый прогон пишется в `etl_runs`.
- Профили крупных и демо-компаний материализуются в `company_profiles` (JSONB с GIN-индексами).
- SQLite — режим для локальной разработки и тестов без Docker (тот же код).
- Docker: `Dockerfile`, `docker-compose.company_profile.yml`, `.env.example`. Добавлены `pyproject.toml` и рекомендуемые роли БД (`db_sql/roles.postgres.sql`).

Контракт (`schema_version` 0.2.0):
- **Добавлено** `CompanyProfile.data_run_id` — id загрузки, к которой привязан профиль.
- **Добавлены** `HealthResponse` и `GET /api/company-profile/health` (без аутентификации, только счётчики).
- **Удалено** `CompanyProfile.restricted`. `NEGATIVEMARK` больше не выдаётся наружу: смысл поля не подтверждён, в выводах оно не используется.
- Порядок контрагентов при равных суммах теперь детерминирован (по id).

Правила и словари:
- **Новое:** `contracts/industry_terms.yaml` — 36 отраслей, 69 префиксов ОКВЭД2, из них 60 сверены с данными кейса. Загрузчик и сопоставление — `services/company_profile/industry_terms.py`.
- **Исправлено** `precious_metals`: убран `46.72.2` (в данных это «металлы в первичных формах»), добавлен `07.29.4`.
- **Исправлено** `agro_food`: убран `02` (лесоводство).
- **Исправлено** `it_telecom`: убран `58` (в данных это издание книг и газет).
- **Исправлено** `consumer_exposure`: вместо всей группы `45.3` только розница `45.11.2` и `45.32`.

Запуск: `uvicorn services.company_profile.main:create_app --factory`.

## 0.1.0

Первая версия: профиль из CSV, признаки, связи, user_context, API, тесты ядра.

## insight 1.0.0 — слой ранжирования, агента, API и интерфейса
- Добавлены `services/insight/` (kb, ranking, lenses, agent, llm, qa, server), `frontend/`, Docker/compose, документация.
- `contracts/news_vocab.py`: темы `taxes`, `regulation` (v1.1); `news_ingest/config/topic_rules_extra.yaml` — дополнительные шаблоны тем; тест синхронизации словарей учитывает role-only темы.
- `data/demo/` — срез CSV кейса; `data/synthetic_users.json` — демо-пользователь `demo` (доступ к 6 демо-компаниям).
- Корневой `Dockerfile` теперь запускает insight-сервис; прежний — `Dockerfile.company_profile`.

## insight 1.1.0 — исправления интерфейса и комплект для жюри
- Меню аватара: смена пользователя без выхода, смена роли, выход; закрытие меню кликом мимо и по Escape (закрывается только верхний слой).
- Истёкшая сессия (рестарт сервера) возвращает на экран входа с сообщением, а не оставляет пустую ленту.
- Адаптивность: шапка и выпадающие меню не выходят за экран (360–1920 px), «Счета и платежи» доступны в мобильном меню, лента не расползается по ширине.
- Колокольчик ведёт в ленту; панель разбора сбрасывает состояние при открытии другого события.
- Исходные PDF банка в `data/bank_pdf/`; просмотр PDF на нужной странице во всплывающем окне, потоковая отдача файлов.
- `requirements.lock.txt`: добавлены beautifulsoup4, lxml и зависимости; `start.bat`/`start.sh`, `docs/DEPLOY.md`.
