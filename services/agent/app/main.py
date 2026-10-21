"""Агент: планировщик -> инструменты -> синтез -> самопроверка, с трассой исполнения."""

from fastapi import FastAPI

app = FastAPI(title="alfa-insight agent", version="0.1.0")


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
