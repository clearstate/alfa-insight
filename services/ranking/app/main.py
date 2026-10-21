"""Ранжирование: поиск, скоринг, объяснение релевантности."""

from fastapi import FastAPI

app = FastAPI(title="alfa-insight ranking", version="0.1.0")


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
