# e2e (Playwright)

Основной сценарий для жюри: вход → лента → инсайт → уточняющий вопрос → смена клиента.

```
tests/e2e/
├── smoke.spec.ts          # сценарий целиком
└── playwright.config.ts   # baseURL = http://localhost:3000 (или VITE-стенд)
```
