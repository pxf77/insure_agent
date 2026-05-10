from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.api.routes import health, signals, watchlist
from backend.app.database import create_db_and_tables


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_db_and_tables()
    yield


def create_app(*, create_tables_on_startup: bool = True) -> FastAPI:
    app = FastAPI(
        title="Hermes Trading Assistant",
        lifespan=lifespan if create_tables_on_startup else None,
    )
    app.include_router(health.router)
    app.include_router(watchlist.router)
    app.include_router(signals.router)
    return app


app = create_app()
