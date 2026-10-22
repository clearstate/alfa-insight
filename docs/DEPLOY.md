# Публикация на бесплатном сервере

Образ самодостаточен: интерфейс, данные (срез CSV, транскрипции и PDF материалов банка, синтетическая лента) внутри. Порт берётся из `PORT`.

**Render / Railway / Fly.io / Koyeb (Docker):** подключить репозиторий → тип «Docker» → `Dockerfile` из корня → переменные: `ALFA_SECRET` (любая длинная строка, чтобы сессии переживали рестарт), при наличии — `LLM_BASE_URL`, `LLM_API_KEY`, имена моделей. Health check: `/api/health`. Памяти достаточно 512 МБ (срез данных); для полных CSV — 1 ГБ.

**VPS:** `git clone … && cd alfa-insight && cp .env.example .env && docker compose up -d --build`. TLS — через reverse-proxy (Caddy/nginx).

После публикации проверьте: вход `demo`/`demo`, открытие разбора, кнопка «Открыть первоисточник» показывает PDF.
