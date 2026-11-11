from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: str, *, pool_size: int | None = None) -> AsyncEngine:
    options: dict[str, Any] = {}
    if pool_size is not None:
        options.update(pool_size=pool_size, max_overflow=0)
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"timeout": 3},
        **options,
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
