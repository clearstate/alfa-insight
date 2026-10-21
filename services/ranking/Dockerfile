FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY README.md ./
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "alfa_insight_ranking.main:app", "--host", "0.0.0.0", "--port", "8000"]
