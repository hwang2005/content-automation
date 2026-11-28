from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from backend.config import Settings


def make_engine(settings: Settings):
    url = settings.database_url.get_secret_value()
    if not url:
        if settings.production:
            raise ValueError("DATABASE_URL is required in production (Supabase PostgreSQL).")
        Path("data").mkdir(exist_ok=True)
        url = "sqlite:///./data/local.db"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if settings.production and not url.startswith("postgresql+psycopg://"):
        raise ValueError("Production requires a PostgreSQL DATABASE_URL.")

    options = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    else:
        # A small app-side pool works with the Supabase session pooler.
        options.update(pool_size=3, max_overflow=2, pool_recycle=300)
        sslmode = make_url(url).query.get("sslmode", "require")
        if settings.production and sslmode not in {"require", "verify-ca", "verify-full"}:
            raise ValueError("Production database connections require SSL.")
        options["connect_args"] = {
            "sslmode": sslmode,
            "connect_timeout": 10,
            "prepare_threshold": None,
        }
    engine = create_engine(url, **options)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def sqlite_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    else:

        @event.listens_for(engine, "connect")
        def postgres_timeout(connection, _):
            # Set this after connecting: some poolers reject libpq's startup
            # `options` parameter. The recommended session pooler retains it.
            with connection.cursor() as cursor:
                cursor.execute("SET statement_timeout = '15s'")
            connection.commit()

    return engine


def ensure_sqlite_schema(engine):
    """Ensure local SQLite databases receive additive columns without losing data."""
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(projects)")}
        if columns and "owner_id" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE projects ADD COLUMN owner_id VARCHAR(128) NOT NULL DEFAULT 'workspace'"
            )
        if columns:
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_projects_owner_id ON projects (owner_id)"
            )


def session_factory(engine):
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
