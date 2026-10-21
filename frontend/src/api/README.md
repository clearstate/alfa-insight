# api

- `schema.d.ts` — типы, сгенерированные из `contracts/openapi.yaml` (`npm run gen:api`). Не редактировать вручную.
- `client.ts` — HTTP-клиент и адаптеры (маппинг DTO → модели UI).

Переключение на мок-данные: `VITE_USE_MOCKS=true` (см. [mocks/](../mocks/)).
