from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session, select

from backend.app.api.deps import get_db_session
from backend.app.models import Watchlist
from backend.app.schemas import WatchlistCreate, WatchlistRead, WatchlistUpdate

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])
SessionDep = Annotated[Session, Depends(get_db_session)]


@router.post("", response_model=WatchlistRead, status_code=status.HTTP_201_CREATED)
def create_watchlist_entry(payload: WatchlistCreate, session: SessionDep) -> Watchlist:
    entry = Watchlist(**payload.model_dump())
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


@router.get("", response_model=list[WatchlistRead])
def list_watchlist_entries(
    session: SessionDep,
    status_filter: str | None = None,
) -> list[Watchlist]:
    statement = select(Watchlist)
    if status_filter is not None:
        statement = statement.where(Watchlist.status == status_filter)
    return list(session.exec(statement).all())


@router.patch("/{entry_id}", response_model=WatchlistRead)
def update_watchlist_entry(
    entry_id: int,
    payload: WatchlistUpdate,
    session: SessionDep,
) -> Watchlist:
    entry = session.get(Watchlist, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="watchlist entry not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    entry.updated_at = datetime.now(UTC)

    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watchlist_entry(entry_id: int, session: SessionDep) -> Response:
    entry = session.get(Watchlist, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="watchlist entry not found")

    session.delete(entry)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
