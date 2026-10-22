# company_profile (участник 1) — v0.3.0

Строит из CSV кейса структурированный профиль компании и пользователя. Профиль отвечает на вопрос «через какие признаки событие может касаться этого бизнеса». Данные хранятся в PostgreSQL (схема `company_profile`), наружу отдаются через HTTP API и SQL-таблицу материализованных профилей.

## Состав

| Файл | Назначение |
|---|---|
| `loader.py`, `validation.py` | чтение CSV, типизация, карантин коллизий id, самоплатежи, отчёт о качестве |
| `okved.py`, `industry_terms.py` | иерархия ОКВЭД2; словарь «термин → префиксы» (`contracts/industry_terms.yaml`) |
| `relationships.py` | связи `same_group`, `shared_person`, `payment_in`, `payment_out` |
| `features.py` + `config/feature_rules.yaml` | `sensitivity_factors` и темы по правилам |
| `access.py` + `config/roles.yaml`, `demo_users.py` | `user_context`, роли, проверка доступа, синтетические пользователи |
| `service.py` | сборка профиля, связей, демо-набор, health |
| `db.py`, `db_sql/` | хранилище PostgreSQL/SQLite, DDL, роли БД |
| `etl.py` | CSV → PostgreSQL |
| `router.py`, `errors.py`, `main.py` | HTTP API, единый формат ошибок, `X-Correlation-ID`, журнал обращений |
| `prompt_view.py` | минимизированный вид профиля для LLM |

## Запуск

Описан в `docs/company_profile_contract.md`, раздел «Запуск». Коротко: `docker compose -f docker-compose.company_profile.yml up --build`.

## Тесты

```bash
uv run pytest tests/company_profile                         # всё, кроме живого PostgreSQL
docker compose -f docker-compose.company_profile.yml --profile test up -d postgres-test
COMPANY_PROFILE_TEST_DATABASE_URL=postgresql://cp:cp@localhost:5433/cp_test uv run pytest tests/company_profile -k postgres
python scripts/run_core_tests.py                            # резервный раннер без pytest
```
