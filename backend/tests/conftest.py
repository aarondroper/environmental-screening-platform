"""Test fixtures backed by a real PostGIS server.

ESP_TEST_DATABASE_URL points at a server where the test role may create
databases (CI: the PostGIS service container; locally: `docker compose up db`).
Each test session gets a freshly created, fully migrated database.
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text

from esp.config import get_settings
from esp.db import get_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
ADMIN_URL = os.environ.get(
    "ESP_TEST_DATABASE_URL", "postgresql+psycopg://esp:esp@localhost:5432/postgres"
)


def alembic_config() -> Config:
    return Config(str(BACKEND_DIR / "alembic.ini"))


def _create_database() -> str:
    name = f"esp_test_{uuid.uuid4().hex[:8]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    return make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)


def _drop_database(url: str) -> None:
    name = make_url(url).database
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def empty_database_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A brand-new database with no migrations applied."""
    url = _create_database()
    monkeypatch.setenv("ESP_DATABASE_URL", url)
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield url
    get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()
    _drop_database(url)


@pytest.fixture
def database_url(empty_database_url: str) -> str:
    """A brand-new database migrated to head."""
    command.upgrade(alembic_config(), "head")
    return empty_database_url
