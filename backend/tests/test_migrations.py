from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from tests.conftest import alembic_config


def _current_revision(url: str) -> str | None:
    engine = create_engine(url)
    with engine.connect() as conn:
        exists = conn.execute(text("SELECT to_regclass('alembic_version')")).scalar()
        revision = (
            conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            if exists
            else None
        )
    engine.dispose()
    return revision


def test_fresh_database_upgrades_to_head_and_round_trips(empty_database_url: str) -> None:
    config = alembic_config()
    head = ScriptDirectory.from_config(config).get_current_head()

    command.upgrade(config, "head")
    assert _current_revision(empty_database_url) == head

    command.downgrade(config, "base")
    assert _current_revision(empty_database_url) is None

    command.upgrade(config, "head")
    assert _current_revision(empty_database_url) == head


def test_migration_history_is_linear() -> None:
    assert len(ScriptDirectory.from_config(alembic_config()).get_heads()) == 1
