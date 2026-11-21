-- PostgreSQL / Supabase upgrade for databases created by the original 001 schema.
-- The migration runner applies this even when 001_initial.sql was already recorded.
-- For a manual upgrade, run this entire file in Supabase SQL Editor as postgres.
-- Existing rows, UUIDs, foreign keys and timestamps are preserved; no tables drop.
-- JSONB normalizes JSON representation (object key order/whitespace is not retained).
-- ALTER TABLE takes a lock; schedule this migration during low traffic.

ALTER TABLE public.projects
    ALTER COLUMN id SET DEFAULT gen_random_uuid();

ALTER TABLE public.article_formats
    ALTER COLUMN id SET DEFAULT gen_random_uuid(),
    ALTER COLUMN samples DROP DEFAULT,
    ALTER COLUMN samples TYPE JSONB USING samples::jsonb,
    ALTER COLUMN samples SET DEFAULT '[]'::jsonb,
    ALTER COLUMN detection_keywords DROP DEFAULT,
    ALTER COLUMN detection_keywords TYPE JSONB USING detection_keywords::jsonb,
    ALTER COLUMN detection_keywords SET DEFAULT '[]'::jsonb;

ALTER TABLE public.generated_posts
    ALTER COLUMN id SET DEFAULT gen_random_uuid(),
    ALTER COLUMN sources DROP DEFAULT,
    ALTER COLUMN sources TYPE JSONB USING sources::jsonb,
    ALTER COLUMN sources SET DEFAULT '[]'::jsonb,
    ALTER COLUMN facts DROP DEFAULT,
    ALTER COLUMN facts TYPE JSONB USING facts::jsonb,
    ALTER COLUMN facts SET DEFAULT '{}'::jsonb,
    ALTER COLUMN format_snapshot DROP DEFAULT,
    ALTER COLUMN format_snapshot TYPE JSONB USING format_snapshot::jsonb,
    ALTER COLUMN format_snapshot SET DEFAULT '{}'::jsonb,
    ALTER COLUMN warnings DROP DEFAULT,
    ALTER COLUMN warnings TYPE JSONB USING warnings::jsonb,
    ALTER COLUMN warnings SET DEFAULT '[]'::jsonb;

ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.article_formats ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.generated_posts ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE
    public.projects, public.article_formats, public.generated_posts
    FROM PUBLIC, anon, authenticated;
