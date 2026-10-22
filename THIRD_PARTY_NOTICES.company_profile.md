# THIRD_PARTY_NOTICES — модуль company_profile (участник 1)

Фрагмент для общего `THIRD_PARTY_NOTICES` (сводит участник 6). Версии фиксирует `uv.lock`.

| Компонент | Назначение | Лицензия |
|---|---|---|
| pandas | обработка CSV и таблиц | BSD-3-Clause |
| NumPy | массивы, индексы связей | BSD-3-Clause |
| PyYAML | конфиги правил, ролей и словаря | MIT |
| FastAPI | HTTP API | MIT |
| Starlette | основа FastAPI | BSD-3-Clause |
| Pydantic | контракт данных | MIT |
| uvicorn | ASGI-сервер | BSD-3-Clause |
| psycopg 3 | драйвер PostgreSQL | LGPL-3.0 |
| PostgreSQL 16 (образ `postgres:16-alpine`) | хранилище | PostgreSQL License |
| uv (образ `ghcr.io/astral-sh/uv`) | сборка окружения | MIT / Apache-2.0 |
| pytest, httpx | тесты | MIT, BSD-3-Clause |

Данные и справочники:
- Датасет кейса «Альфа Будущее» (Альфа-Банк × Changellenge): `df_Uid_data_hack.csv`, `df_Fid_Uid_link_hack.csv`, `df_Uid_payment_hack.csv`. Данные обезличены и используются только в рамках хакатона; в репозиторий не коммитятся.
- ОКВЭД2 (ОК 029-2014). Используются границы разделов и префиксы кодов в `feature_rules.yaml` и `contracts/industry_terms.yaml`.

Модели LLM, эмбеддинги и внешние AI-сервисы модуль не использует.

Смоделированные интеграции: аутентификация через заголовок `X-User-ID` и синтетические пользователи (`demo_users.py`) — заглушка вместо интернет-банка.
