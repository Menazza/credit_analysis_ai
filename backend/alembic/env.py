from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from alembic import context
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env so DATABASE_URL is set (backend/.env or project root)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
except ImportError:
    pass

from app.db.session import Base
from app.models import *  # noqa: F401, F403
from app.config import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
settings = get_settings()
# Alembic uses sync driver (psycopg2); keep original URL with sslmode for Neon
sync_url = os.getenv("DATABASE_URL") or settings.database_url.replace("+asyncpg", "")
config.set_main_option("sqlalchemy.url", sync_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Use sync engine (psycopg2) so Neon URL with sslmode=require works."""
    from sqlalchemy import create_engine
    url = config.get_main_option("sqlalchemy.url")
    connectable = create_engine(url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        do_run_migrations(connection)
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
