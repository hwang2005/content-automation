"""Apply ordered SQL migrations. Runs before uvicorn on Render, never on API requests."""

from pathlib import Path

from sqlalchemy import text

from backend.config import get_settings
from backend.database import ensure_sqlite_schema, make_engine
from backend.models import Base


def migrate():
    engine = make_engine(get_settings())
    try:
        if engine.dialect.name == "sqlite":
            Base.metadata.create_all(engine)
            ensure_sqlite_schema(engine)
            print("Local SQLite tables ready. Production uses Supabase PostgreSQL.")
            return
        with engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(725402168)"))
            connection.exec_driver_sql(
                "CREATE TABLE IF NOT EXISTS public.schema_migrations "
                "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            connection.exec_driver_sql("ALTER TABLE public.schema_migrations ENABLE ROW LEVEL SECURITY")
            connection.exec_driver_sql("REVOKE ALL ON public.schema_migrations FROM anon, authenticated")
            applied = set(connection.execute(text("SELECT version FROM public.schema_migrations")).scalars())
            for path in sorted((Path(__file__).parent.parent / "migrations").glob("*.sql")):
                if path.name in applied:
                    continue
                connection.exec_driver_sql(path.read_text(encoding="utf-8"))
                connection.execute(
                    text("INSERT INTO public.schema_migrations(version) VALUES (:version)"),
                    {"version": path.name},
                )
                print(f"Applied {path.name}")
        print("Supabase migrations ready.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    migrate()
