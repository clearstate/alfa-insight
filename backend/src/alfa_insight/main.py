from fastapi import FastAPI

app = FastAPI(
    title="Alfa Insight",
    description="Personalized business news analytics",
    version="0.1.0",
)


@app.get("/health", tags=["Health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
