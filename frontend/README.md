# frontend

**Владелец:** участник 5

## Запуск

```bash
npm ci
npm run gen:api   # типы из contracts/openapi.yaml
npm run dev
```

Переменные: `VITE_API_BASE_URL`, `VITE_USE_MOCKS` (см. корневой `.env.example`).

## Структура

| Каталог | Содержимое |
|---|---|
| `src/api/` | клиент, сгенерированный из OpenAPI, и адаптеры |
| `src/mocks/` | MSW-моки (TEMP) |
| `src/pages/` | вход, главный экран, лента, инсайт, сравнение |
| `src/components/` | карточки, метки claim_type, трасса, чипы вопросов |
| `src/styles/` | дизайн-токены |

E2E-сценарии: [tests/e2e](../tests/e2e/).
