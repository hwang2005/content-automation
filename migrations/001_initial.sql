-- PostgreSQL / Supabase bootstrap schema.
-- Run the entire file in Supabase SQL Editor using the postgres role, or use
-- python -m backend.migrate. No SQLite or MySQL syntax is used in this file.
-- gen_random_uuid() is built into PostgreSQL 13+; no extension is required.
-- IF NOT EXISTS allows this bootstrap to run again after a manual SQL Editor run.
-- It does not upgrade existing columns: use 002_postgresql_defaults_jsonb.sql
-- for databases created with the earlier version of this schema.

CREATE TABLE IF NOT EXISTS public.projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(120) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    writing_guide TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.article_formats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    name VARCHAR(120) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    structure TEXT NOT NULL,
    writing_guide TEXT NOT NULL DEFAULT '',
    samples JSONB NOT NULL DEFAULT '[]'::jsonb,
    detection_keywords JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_article_formats_project_id
    ON public.article_formats (project_id);

CREATE TABLE IF NOT EXISTS public.generated_posts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    format_id UUID REFERENCES public.article_formats(id) ON DELETE SET NULL,
    source_type VARCHAR(30) NOT NULL CHECK (source_type IN ('url', 'facebook_paste')),
    source_url TEXT,
    source_text TEXT NOT NULL,
    source_title TEXT NOT NULL,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    facts JSONB NOT NULL DEFAULT '{}'::jsonb,
    selected_format_name VARCHAR(120) NOT NULL,
    selection_reason TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    format_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    generated_content TEXT NOT NULL,
    original_content TEXT NOT NULL,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    additional_instructions TEXT NOT NULL DEFAULT '',
    model VARCHAR(120) NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_generated_posts_project_id
    ON public.generated_posts (project_id);
CREATE INDEX IF NOT EXISTS ix_generated_posts_created_at
    ON public.generated_posts (created_at);

-- This application uses a private backend connection, not browser Data API access.
-- RLS intentionally has no anon/authenticated policies. Keep these tables private.
ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.article_formats ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.generated_posts ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE
    public.projects, public.article_formats, public.generated_posts
    FROM PUBLIC, anon, authenticated;
