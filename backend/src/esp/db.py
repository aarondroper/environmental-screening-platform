from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from esp.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def get_session() -> Iterator[Session]:
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as session:
        yield session


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """Alembic filter: ignore tables the app does not own (PostGIS, TIGER geocoder, topology)."""
    return not (type_ == "table" and reflected and compare_to is None)
