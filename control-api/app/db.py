import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlmodel import Session, create_engine

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://agent_scanner:agent_scanner@localhost:5432/agent_scanner",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# The revision that represents the schema as it existed before Alembic was
# introduced. An already-populated database from that era has no
# alembic_version row, so it gets stamped with this revision (not "head") --
# any migrations added later still run against it.
BASELINE_REVISION = "0001_baseline"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    return config


def _bootstrap_existing_database(config: Config) -> None:
    """Older dev databases were created by `create_all()` and have the tables
    but no `alembic_version`. Stamp them at the baseline instead of replaying
    the baseline and failing on "table already exists"."""
    inspector = inspect(engine)
    if inspector.has_table("alembic_version"):
        return
    if inspector.has_table("scan") or inspector.has_table("agentconfig"):
        command.stamp(config, BASELINE_REVISION)


def init_db() -> None:
    """Bring the schema up to date by applying pending migrations. Never
    recreates the database, so existing rows survive schema changes."""
    config = _alembic_config()
    _bootstrap_existing_database(config)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def get_session():
    with Session(engine) as session:
        yield session
