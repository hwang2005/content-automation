-- Run with the Supabase postgres role. The browser never connects to these tables.
CREATE TABLE public.projects (
    id uuid PRIMARY KEY,
    name varchar(120) NOT NULL,
    description text NOT NULL DEFAULT '',
    writing_guide text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.article_formats (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    name varchar(120) NOT NULL,
    description text NOT NULL DEFAULT '',
    structure text NOT NULL,
    writing_guide text NOT NULL DEFAULT '',
    samples json NOT NULL DEFAULT '[]',
    detection_keywords json NOT NULL DEFAULT '[]',
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_article_formats_project_id ON public.article_formats(project_id);

CREATE TABLE public.generated_posts (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    format_id uuid REFERENCES public.article_formats(id) ON DELETE SET NULL,
    source_type varchar(30) NOT NULL CHECK (source_type IN ('url', 'facebook_paste')),
    source_url text,
    source_text text NOT NULL,
    source_title text NOT NULL,
    sources json NOT NULL DEFAULT '[]',
    facts json NOT NULL DEFAULT '{}',
    selected_format_name varchar(120) NOT NULL,
    selection_reason text NOT NULL,
    confidence double precision NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    format_snapshot json NOT NULL DEFAULT '{}',
    generated_content text NOT NULL,
    original_content text NOT NULL,
    warnings json NOT NULL DEFAULT '[]',
    additional_instructions text NOT NULL DEFAULT '',
    model varchar(120) NOT NULL,
    input_tokens integer NOT NULL DEFAULT 0,
    output_tokens integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_generated_posts_project_id ON public.generated_posts(project_id);
CREATE INDEX ix_generated_posts_created_at ON public.generated_posts(created_at);

-- Do not expose workspace data through the Supabase public Data API.
ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.article_formats ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.generated_posts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.projects, public.article_formats, public.generated_posts FROM anon, authenticated;
