"""Optional PostgreSQL integration tests; every test gets a new disposable database.

TEST_POSTGRES_ADMIN_DSN must point to a local test server with the Supabase roles
anon/authenticated already present. Never use production credentials here.
"""

import os
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from backend import migrate as migrations
from backend.models import ArticleFormat, GeneratedPost, Project

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
BOOTSTRAP = (MIGRATIONS / "001_initial.sql").read_text(encoding="utf-8")
UPGRADE = (MIGRATIONS / "002_postgresql_defaults_jsonb.sql").read_text(encoding="utf-8")
JSON_COLUMNS = (
    ("article_formats", "samples"),
    ("article_formats", "detection_keywords"),
    ("generated_posts", "sources"),
    ("generated_posts", "facts"),
    ("generated_posts", "format_snapshot"),
    ("generated_posts", "warnings"),
)


def test_json_model_types_match_each_database():
    for table, column in JSON_COLUMNS:
        model = ArticleFormat if table == "article_formats" else GeneratedPost
        data_type = model.__table__.c[column].type
        assert data_type.compile(dialect=postgresql.dialect()) == "JSONB"
        assert data_type.compile(dialect=sqlite.dialect()) == "JSON"


@pytest.fixture
def postgres_database():
    admin_dsn = os.getenv("TEST_POSTGRES_ADMIN_DSN")
    if not admin_dsn:
        pytest.skip("Set TEST_POSTGRES_ADMIN_DSN to run isolated PostgreSQL integration tests.")
    if conninfo_to_dict(admin_dsn).get("host") not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("PostgreSQL integration tests require a disposable localhost test server.")

    database_name = "content_studio_test_" + uuid4().hex
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        roles = admin.execute(
            "SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')"
        ).fetchall()
        if len(roles) != 2:
            pytest.fail("Create NOLOGIN roles anon and authenticated on the local test server first.")
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        dsn = make_conninfo(admin_dsn, dbname=database_name)
        engine = create_engine(
            "postgresql+psycopg://", creator=lambda: psycopg.connect(dsn, prepare_threshold=None)
        )
        try:
            yield engine
        finally:
            engine.dispose()
            # Only remove the randomly named database created by this fixture.
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))


def assert_postgresql_schema(connection):
    for table, column in JSON_COLUMNS:
        kind = connection.execute(text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table AND column_name = :column"
        ), {"table": table, "column": column}).scalar_one()
        assert kind == "jsonb"
    for table in ("projects", "article_formats", "generated_posts"):
        default = connection.execute(text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table AND column_name = 'id'"
        ), {"table": table}).scalar_one()
        assert "gen_random_uuid()" in default
        assert connection.execute(text(
            "SELECT relrowsecurity FROM pg_class WHERE oid = CAST(:table AS regclass)"
        ), {"table": f"public.{table}"}).scalar_one() is True
        for role in ("anon", "authenticated"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert connection.execute(text(
                    "SELECT has_table_privilege(:role, :table, :privilege)"
                ), {"role": role, "table": f"public.{table}", "privilege": privilege}).scalar_one() is False
    owner_default = connection.execute(text(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'projects' AND column_name = 'owner_id'"
    )).scalar_one()
    assert "'workspace'" in owner_default


def run_migrations(monkeypatch, engine):
    # Use only the isolated fixture's engine, never the real DATABASE_URL/.env.
    monkeypatch.setattr(migrations, "get_settings", lambda: None)
    monkeypatch.setattr(migrations, "make_engine", lambda _: engine)
    migrations.migrate()


def test_sql_editor_bootstrap_replay_and_backend_runner(postgres_database, monkeypatch):
    engine = postgres_database
    with engine.begin() as connection:
        connection.exec_driver_sql(BOOTSTRAP)
        connection.exec_driver_sql(BOOTSTRAP)
        # SQL Editor inserts can omit UUIDs; JSONB defaults must be decoded as JSON.
        project_id = connection.execute(text(
            "INSERT INTO public.projects(name) VALUES ('SQL Editor test') RETURNING id"
        )).scalar_one()
        assert isinstance(project_id, UUID)
        article = connection.execute(text(
            "INSERT INTO public.article_formats(project_id, name, structure) "
            "VALUES (:project_id, 'Hội thảo', 'Tiêu đề và nội dung') "
            "RETURNING id, samples, detection_keywords"
        ), {"project_id": project_id}).one()
        assert isinstance(article.id, UUID)
        assert article.samples == [] and article.detection_keywords == []

    # Manual bootstrap does not record migration versions; the runner must still work.
    run_migrations(monkeypatch, engine)
    run_migrations(monkeypatch, engine)
    with engine.begin() as connection:
        assert_postgresql_schema(connection)
        assert connection.execute(text(
            "SELECT version FROM public.schema_migrations ORDER BY version"
        )).scalars().all() == ["001_initial.sql", "002_postgresql_defaults_jsonb.sql", "003_project_owner.sql"]

    # Verify the actual PostgreSQL JSONB schema remains compatible with the ORM.
    with Session(engine) as session:
        project = session.get(Project, project_id)
        assert project.name == "SQL Editor test"
        article_format = session.get(ArticleFormat, article.id)
        article_format.samples = ["Bài mẫu tiếng Việt 🎯"]
        session.commit()
        session.expire_all()
        assert session.get(ArticleFormat, article.id).samples == ["Bài mẫu tiếng Việt 🎯"]


def test_existing_json_database_upgrade_preserves_rows(postgres_database, monkeypatch):
    engine = postgres_database
    # Reproduce the original schema: JSON columns and application-generated UUIDs (before owner_id).
    legacy = BOOTSTRAP.replace("UUID PRIMARY KEY DEFAULT gen_random_uuid()", "UUID PRIMARY KEY")
    legacy = legacy.replace("JSONB", "JSON").replace("::jsonb", "::json")
    project_id, format_id, post_id = uuid4(), uuid4(), uuid4()
    with engine.begin() as connection:
        connection.exec_driver_sql(legacy)
        connection.exec_driver_sql(
            "CREATE TABLE public.schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now()); "
            "INSERT INTO public.schema_migrations(version) VALUES ('001_initial.sql');"
        )
        connection.execute(text(
            "INSERT INTO public.projects(id, name, writing_guide) VALUES (:id, 'Dự án đã có', 'Không đổi hướng dẫn.')"
        ), {"id": project_id})
        connection.execute(text(
            "INSERT INTO public.article_formats(id, project_id, name, structure, samples, detection_keywords) "
            "VALUES (:id, :project_id, 'Hội thảo', 'Tiêu đề → thông tin', '[\"Bài mẫu cũ 🎯\"]'::json, '[\"workshop\"]'::json)"
        ), {"id": format_id, "project_id": project_id})
        connection.execute(text(
            "INSERT INTO public.generated_posts("
            "id, project_id, format_id, source_type, source_text, source_title, sources, facts, "
            "selected_format_name, selection_reason, confidence, format_snapshot, generated_content, "
            "original_content, warnings, model"
            ") VALUES ("
            ":id, :project_id, :format_id, 'facebook_paste', 'Thông tin nguồn.', 'Hội thảo AI', "
            "'[{\"title\": \"Nguồn gốc\", \"text\": \"Thông tin nguồn.\"}]'::json, "
            "'{\"items\": [{\"label\": \"Phí\", \"value\": \"Miễn phí\"}]}'::json, "
            "'Hội thảo', 'Đúng mục đích.', 0.9, '{\"name\": \"Hội thảo\"}'::json, "
            "'Nội dung đã sửa ✨', 'Nội dung ban đầu 🎯', '[\"Cần kiểm tra hạn chót.\"]'::json, 'test-model'"
            ")"
        ), {"id": post_id, "project_id": project_id, "format_id": format_id})
    with engine.connect() as connection:
        before = connection.execute(select(GeneratedPost.__table__)).mappings().one()

    # 001 is already applied, so 002 and 003 must upgrade without rerunning 001.
    run_migrations(monkeypatch, engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(UPGRADE)  # A repeated manual upgrade also succeeds.
        assert_postgresql_schema(connection)
        after = connection.execute(select(GeneratedPost.__table__)).mappings().one()
        assert dict(after) == dict(before)
        assert after["id"] == post_id and after["project_id"] == project_id
        assert connection.execute(text("SELECT owner_id FROM public.projects WHERE id = :id"), {"id": project_id}).scalar_one() == "workspace"
    with Session(engine) as session:
        assert session.get(ArticleFormat, format_id).samples == ["Bài mẫu cũ 🎯"]
        session.delete(session.get(ArticleFormat, format_id))
        session.commit()
        assert session.get(GeneratedPost, post_id).format_id is None
        session.delete(session.get(Project, project_id))
        session.commit()
        assert session.get(GeneratedPost, post_id) is None
