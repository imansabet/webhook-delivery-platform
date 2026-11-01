from fastapi import FastAPI

app = FastAPI(title="webhook-delivery-platform")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
