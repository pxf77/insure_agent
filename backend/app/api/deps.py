from collections.abc import Generator

from sqlmodel import Session

from backend.app.database import get_session


def get_db_session() -> Generator[Session, None, None]:
    yield from get_session()
