from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from webhook_platform.db import SessionDep, create_engine, create_sessionmaker
from webhook_platform.endpoints import router as endpoints_router
from webhook_platform.events import router as events_router
from webhook_platform.tenants import router as tenants_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = create_engine()
    app.state.sessionmaker = create_sessionmaker(engine)
    yield
    await engine.dispose()


app = FastAPI(title="webhook-delivery-platform", lifespan=lifespan)
app.include_router(tenants_router)
app.include_router(endpoints_router)
app.include_router(events_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready(session: SessionDep) -> dict[str, str]:
    try:
        await session.execute(text("select 1"))
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ready"}
