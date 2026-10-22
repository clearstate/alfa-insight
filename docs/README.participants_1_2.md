# Alfa Insight — модуль company_profile (участник 1), v0.3.0

Профиль компании и пользователя для персонализации новостной аналитики. Модуль отвечает на вопрос «через какие признаки событие может касаться этого бизнеса».

- Контракт для команды: `docs/company_profile_contract.md`. Pydantic-модели: `contracts/company_profile.py`. Словарь отраслей: `contracts/industry_terms.yaml`.
- Аудит данных: `docs/data_audit.md`. Обоснование признаков: `docs/feature_provenance.md`. Примеры ответов на реальных данных: `docs/examples/`.
- Модуль: `services/company_profile/README.md`. Изменения: `CHANGELOG.md`.

Быстрый старт:

```bash
cp .env.example .env && cp /path/to/*.csv data/raw/ && uv lock
docker compose -f docker-compose.company_profile.yml up --build
```


---
## Модули
- `services/company_profile` — профиль компании (участник 1), см. выше.
- `services/news_ingest` — конвейер новостей и аналитики банка (участник 2): `services/news_ingest/README.md`, контракт `docs/news_item_contract.md`, передача участнику 3 — `docs/handoff_participant3.md`.
