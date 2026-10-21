"""Ингестия: парсеры новостей, разбор PDF, нормализация, дедупликация."""

from fastapi import FastAPI

app = FastAPI(title="alfa-insight ingestion", version="0.1.0")


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
