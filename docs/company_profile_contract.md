# Контракт company_profile — для участников 3, 4, 5, 6

Версия схемы `0.3.0` (изменения — `CHANGELOG.md`). Pydantic-модели: `contracts/company_profile.py`. Владелец модуля — участник 1, владелец `contracts/` — участник 6.
Примеры реальных ответов на обезличенных данных кейса: `docs/examples/`.

## API

| Метод | Ответ | Ошибки |
|---|---|---|
| `GET /api/users/me/companies` | `UserCompaniesResponse`: роль, приоритетные темы, компании пользователя со статусом `ok`, `not_found` или `quarantined` | 401 |
| `GET /api/companies/{company_id}/profile` | `CompanyProfile` | 401, 403, 404, 422 |
| `GET /api/companies/{company_id}/related?limit=100&types=same_group&types=payment_in` | `RelatedResponse` | 401, 403, 404, 422 |
| `GET /api/companies/demo?n=5` | `list[DemoCompany]`, только при `COMPANY_PROFILE_DEMO_ENDPOINTS=1` | 401, 404 |
| `GET /api/company-profile/health` | `HealthResponse`: хранилище, `data_run_id`, счётчики, совпадение правил с ETL. Без аутентификации | — |

Порядок проверок:
1. Нет `X-User-ID` или пользователь неизвестен → 401 `unauthenticated`.
2. Компания неизвестна → 404 `company_not_found`; id в карантине → 422 `company_id_ambiguous`.
3. Компания не входит в `company_ids` пользователя → 403 `forbidden`.

Формат ошибки: `{"error": {"code", "message", "details", "correlation_id"}}`. `X-Correlation-ID` берётся из запроса или генерируется и всегда возвращается в ответе.
Аутентификация в прототипе — заглушка через `X-User-ID`. **Участник 6:** заменить на общую сессию, сохранив `UserContext`.
`related` возвращает id контрагентов, к профилям которых у пользователя нет доступа: id обезличены, а профиль такой компании всё равно вернёт 403.

## Главное в схеме

Значение любого поля — объект `Attr`: `{value, claim_type, source_file, source_row_id, source_field, as_of, method, confidence}`.
- `claim_type`: `fact` (поле CSV), `inference` (детерминированное правило, **не LLM**), `unknown`.
- `source_row_id` = `line:N`, номер строки в исходном CSV (заголовок — строка 1).
- `as_of` всегда `null`: дат в данных нет.

Блоки профиля: `industry` (код, иерархия, раздел, совпавшие отраслевые правила), `geography`, `size`, `legal`, `bank_relationship`, `foreign_trade`, `group`, `related_by_people`, `counterparties` (входящие и исходящие: топ-10, доли, покрытие известными контрагентами), `sensitivity_factors`, `topics`, `data_gaps`, `reliability_notes`, `quality_issues`. Поле `data_run_id` указывает загрузку данных (`company_profile.etl_runs`), на которой построен профиль.

С версии 0.2.0 `NEGATIVEMARK` в профиль не входит: смысл не подтверждён, и наружу это поле не выдаётся.

## Что берёт каждый участник

**Участник 3 (агент).**
- Инструмент `get_company_profile` возвращает полный профиль для трассировки. В промпт LLM передаётся только `build_prompt_view(profile)` из `services/company_profile/prompt_view.py`: без id контрагентов и физлиц, выручка — только порядок величины.
- Для раздела «Почему это важно для компании» удобно опираться на `sensitivity_factors[].rationale`, `level` и `confidence`, а также на `data_gaps`.
- Ссылка на источник в выводе: `rule_id` плюс `based_on[]` (файл, строка, поле).
- Признаки модуля имеют `claim_type = inference`. Если агент перефразирует их с помощью LLM, это уже `ai_inference` по сквозной шкале.

**Участник 4 (ранжирование).**
- Основной вход: `profile.topics[]` = `{topic, weight 0..1, sources[]}`. Дополнительно — `industry.okved_levels`, `industry.okved_section`, `geography.region`, `foreign_trade.countries`, а также поставщики и покупатели в `supply_chain_industries.details`.
- Объяснение ранга: `sources[].source` (`industry:<rule_id>` или `factor:<code>`).
- Цепочка поставок (с 0.3.0): `industry_terms.match_supply_chain(news.okved_prefixes, profile)` возвращает совпадения с полными кодами контрагентов. Каждое совпадение содержит направление (`suppliers` или `customers`) и долю оборота, их можно использовать в объяснении ранга. Структура описана моделью `SupplyChainDetails`.
- Роль пользователя: `UserCompaniesResponse.priority_topics` (порядок = приоритет).

**Участник 5 (UI).**
- Показывать `claim_type` бейджем («данные», «правило», «нет данных») и `confidence`.
- `reliability_notes` и `data_gaps` выводить в блоке «Ограничения данных».
- Список компаний для переключателя клиента — `GET /api/users/me/companies`.
- Суммы показывать с подписью «единицы не подтверждены» до ответа организаторов.

**Участник 6 (интеграция).** Подключение: `errors.install(app)`, `app.include_router(router)`, `app.state.profile_service = build_service()` из `services/company_profile/main.py`. Стенд модуля описан в `docker-compose.company_profile.yml`, роли БД — в `services/company_profile/db_sql/roles.postgres.sql`.

## Отрасли в news_item: формат и словарь (ответ на запрос участника 2/4)

**Разделы ОКВЭД (буквы) как основной ключ не подтверждаю.** Раздел слишком грубый. В G попадают и розница (47), и опт автозапчастей (45.31), и оптовая торговля (46): на демо-компании U_25835 именно из-за этого ложно сработало правило потребительского сектора. Отрасли контрагентов в профиле тоже заданы двухзначными классами (`supply_chain_industries.details[].okved_division`), так что по одним разделам цепочка поставок не сопоставится.

Предлагаемый формат (решение — за участником 2 как владельцем `news_item` и участником 6):
- `okved_prefixes: list[str]` — **основной ключ**: префиксы ОКВЭД2 уровня класса и глубже (`"47"`, `"45.32"`, `"07.29.4"`);
- `okved_sections: list[str]` — буквы разделов, **выводятся** из префиксов функцией `sections_for`, только для грубой фильтрации и UI.

Правило сопоставления: префикс новости входит в `profile.industry.okved_levels` или в `okved_division` контрагента. Реализация — `services/company_profile/industry_terms.py::match_company`.

Словарь: `contracts/industry_terms.yaml`, 36 отраслей, 69 префиксов.
- **60 префиксов сверены с данными** (`verified: data`): код встречается в файле юрлиц, смысл проверен по `MAINOKVED_NAME`, пример лежит в `example_okved`.
- **9 префиксов только по классификатору** (`verified: classifier`), в данных их нет: `19.2`, `49.5`, `05`, `24.41`, `32.12`, `49.1`, `51`, `39`, `65`. Их нужно сверить с официальным справочником ОКВЭД2.
- `ambiguous_terms` (например «газ», «банк», «порт», «связи») сами по себе отрасль не задают.
- Генерация и пересверка: `python scripts/build_industry_terms.py <папка с CSV>`. Проверки — `tests/company_profile/test_industry_terms.py`.

## Словарь тем (v1)

`agro, auto_market, bond_market, business_activity, chemicals, commodities, construction, consumer_credit, consumer_demand, counterparty_risk, credit_conditions, deposit_rates, export, financial_regulation, food_prices, foreign_trade, fuel_prices, fx_rates, gdp, gold, import_substitution, inflation, it, key_rate, labor_market, liquidity, logistics, metals, mortgage, oil_gas, real_estate, regulation, retail, sanctions, taxes, tourism, wage_inflation, wholesale_trade`.

Темы `taxes` и `regulation` есть только в приоритетах ролей: из профиля компании они не выводятся. **Участникам 2 и 4:** при классификации новостей и материалов банка использовать этот словарь или прислать маппинг.

## Роли и приоритетные темы (`config/roles.yaml`)

| Роль | Приоритетные темы |
|---|---|
| owner | gdp, sanctions, regulation, counterparty_risk, key_rate, business_activity |
| ceo | gdp, consumer_demand, business_activity, sanctions, regulation, commodities |
| cfo | key_rate, credit_conditions, bond_market, inflation, fx_rates, liquidity |
| chief_accountant | taxes, regulation, financial_regulation, wage_inflation, labor_market |
| treasury | fx_rates, liquidity, deposit_rates, key_rate, bond_market, gold |
| other_c_level | business_activity, gdp, labor_market |
| other | — |

Синтетические учётные записи лежат в `data/synthetic_users.json`. Файл сгенерирован командой `scripts/company_profile_cli.py users` из демо-набора: `u_cfo_demo`, `u_treasury_demo`, `u_accountant_demo`, `u_owner_demo`, `u_ceo_demo`, `u_other_demo` (последний без компаний, для проверки 403).

## Демо-компании (реальные обезличенные данные, `docs/examples/demo_companies.json`)

| company_id | Слот | ОКВЭД | Регион | Контраст |
|---|---|---|---|---|
| U_25835 | credit_and_fx | 45.31.1, опт автозапчастей | Москва | кредиты и лизинг + ВЭД (ОАЭ, Китай, Италия) |
| U_99802 | no_credit_no_fx | 68.20.2, аренда недвижимости | Московская обл. | нет кредитов и ВЭД, есть депозиты |
| U_212593 | consumer_sector | 56.10.1, рестораны | Москва | потребительский сектор, есть кредиты |
| U_58207 | deposits_treasury | 46.90, опт неспециализированный | Москва | депозиты + кредиты + ВЭД |
| U_51606 | credit_no_fx | 41.20.9, строительство | Татарстан | кредиты без ВЭД, другой регион |
| U_150736 | fx_no_credit | 17.21, гофрокартон | Москва | ВЭД без кредитов, производство |

Выбор детерминирован: компании с выручкой от 15 млрд и `CL_TYPE = CLIENT`, приоритет у компаний с большим числом известных контрагентов и с разными разделами ОКВЭД.

## Хранилище: PostgreSQL

Схема `company_profile`. DDL генерируется из `db.py`; справочная копия — `services/company_profile/db_sql/schema.postgres.sql`. Миграцию применяет ETL.

| Таблица | Содержимое |
|---|---|
| `etl_runs` | прогоны ETL: статус, время, статистика качества, хэш правил |
| `companies` | нормализованные юрлица; колонки — имена из CSV в нижнем регистре, плюс `source_line` |
| `quarantined_companies`, `company_issues` | карантин id и проблемы качества по компаниям |
| `person_links` | связи физлицо ↔ компания |
| `payments`, `self_payments` | агрегированные пары плательщик → получатель без самоплатежей; самоплатежи отдельно |
| `users`, `user_companies` | синтетические пользователи и их доступ к компаниям |
| `company_profiles` | материализованные профили (JSONB) и поля для поиска: `okved_levels`, `topic_names` (GIN), `is_large_business`, `okved_section`, `region` |
| `demo_companies` | демо-набор |

Как работает:
- **ETL** перезагружает данные в одной транзакции, поэтому читатели не видят частичного состояния. Сбойный прогон получает статус `failed`, а данные предыдущего успешного прогона остаются.
- **API** при старте читает последнюю успешную загрузку в память, а запросы обслуживает без обращений к БД. Профили, которые отдаёт API, совпадают с материализованными: проверено на реальных данных через SQLite.
- **Хэш правил.** Если `feature_rules.yaml` изменён после ETL, health вернёт `rules_match_etl: false`. В этом случае ETL нужно перезапустить.
- **Объём материализации.** `company_profiles` по умолчанию содержит 115 крупных компаний и демо-компании (`--profiles large`). API строит профиль любой компании на лету.

Замеры на реальных данных (SQLite, в этой среде):
- ETL — 38 с;
- чтение загрузки при старте API — 7,6 с;
- файл БД — 154 МБ;
- пиковая память одного сервиса около 0,5 ГБ.

На PostgreSQL эти замеры не выполнялись.

### SQL для участников 3 и 4 (роль `company_profile_reader`)

```sql
-- компании, которых касается новость с префиксами ОКВЭД 47 и 56
SELECT company_id, okved_code FROM company_profile.company_profiles WHERE okved_levels ?| array['47','56'];
-- компании с темой key_rate и её весом
SELECT p.company_id, (t->>'weight')::float AS weight
FROM company_profile.company_profiles p, jsonb_array_elements(p.profile->'topics') t
WHERE t->>'topic' = 'key_rate' ORDER BY weight DESC;
-- уровень признака
SELECT p.company_id, f->>'level' AS level, f->>'confidence' AS confidence
FROM company_profile.company_profiles p, jsonb_array_elements(p.profile->'sensitivity_factors') f
WHERE f->>'code' = 'rate_sensitivity';
-- цепочка поставок: поставщики из отраслей с префиксом 45.3 (точное совпадение уровня кода)
SELECT p.company_id, c->>'okved_code' AS okved_code, (c->>'share_of_known')::float AS share
FROM company_profile.company_profiles p,
     jsonb_array_elements(p.profile->'sensitivity_factors') f,
     jsonb_array_elements(f->'details'->'supplier_codes') c
WHERE f->>'code' = 'supply_chain_industries' AND c->'okved_levels' ? '45.3'
ORDER BY share DESC;
-- последняя успешная загрузка
SELECT run_id, finished_at, counters FROM company_profile.etl_runs
WHERE status = 'success' ORDER BY finished_at DESC LIMIT 1;
```

Права пользователей (какие компании видит ЛПР) проверяет API, а не БД. Поэтому UI работает только через API. Таблицы `users`, `user_companies`, `payments` и `companies` читателям не выдаются.

### Запуск

```bash
cp .env.example .env              # задать POSTGRES_PASSWORD
cp /path/to/*.csv data/raw/       # три CSV кейса
uv lock                           # один раз (нужна сеть); uv.lock закоммитить
docker compose -f docker-compose.company_profile.yml up --build
curl localhost:8001/api/company-profile/health
curl -H "X-User-ID: u_cfo_demo" localhost:8001/api/companies/U_25835/profile
```

Без Docker:

```bash
uv sync
DATABASE_URL=postgresql://... uv run python -m services.company_profile.etl --data-dir data/raw
DATABASE_URL=postgresql://... uv run uvicorn services.company_profile.main:create_app --factory --port 8001
```

Для локальной отладки без PostgreSQL подходит `DATABASE_URL=sqlite:///data/company_profile.db`.

## Зависимости

Список — в `pyproject.toml`:
- ядро: pandas, numpy, PyYAML;
- API: FastAPI, Pydantic v2, uvicorn;
- PostgreSQL: psycopg 3;
- тесты: pytest, httpx.

`uv.lock` в архиве нет: в моей среде нет сети. Его создаёт команда `uv lock`, без него Docker-сборка (`uv sync --frozen`) не пройдёт. Сторонние компоненты перечислены в `THIRD_PARTY_NOTICES.company_profile.md`.

## Безопасность (место в архитектуре)

- Разграничение прав: каждый запрос проверяется по `user.company_ids` (403).
- Журнал обращений: логгер `company_profile.audit`, JSON с полями `event`, `user_id`, `company_id`, `path`, `outcome`, `correlation_id`. Данные профиля в лог не пишутся.
- Минимизация данных: `prompt_view` для LLM; `NEGATIVEMARK` не выдаётся наружу; геоданные физлиц не загружаются.
- Роли БД: запись только у `company_profile_etl`, чтение у `company_profile_api` и `company_profile_reader`. Сырые таблицы читателям не выдаются (`db_sql/roles.postgres.sql`).
- Секреты: только переменные окружения (`DATABASE_URL`, `.env` в `.gitignore`).

## Открытые вопросы к команде

0. **Участнику 6.** Принять схему `company_profile` в общий PostgreSQL, применить `roles.postgres.sql`, сгенерировать и закоммитить `uv.lock`, прогнать `pytest` (включая `test_store_postgres.py` на тестовой БД).
1. **Участнику 6.** Сквозная шкала `claim_type` (`fact | bank_view | ai_inference | unknown`) не различает правило и LLM. Предлагаю добавить `rule_inference` или отображать `inference` модуля как отдельное значение. Нужно решение до v0.2.
2. **Участнику 6.** Общий механизм аутентификации и ошибок: `errors.py` модуля — временный.
3. **Участнику 4.** Подходят ли веса тем (отрасль 1,0; признак high 0,8, medium 0,5; цепочка поставок 0,5 × доля)?
4. **Участнику 5.** Нужна ли отдельная ручка с компактной карточкой компании для шапки экрана, или хватит `users/me/companies`?
