from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.api.routes import health
from backend.app.database import create_db_and_tables


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_db_and_tables()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Hermes Trading Assistant", lifespan=lifespan)
    app.include_router(health.router)
    return app


app = create_app()
