-- Add per-account project ownership for Supabase Google OAuth while keeping
-- existing password-authenticated workspace projects under 'workspace'.
ALTER TABLE public.projects
    ADD COLUMN IF NOT EXISTS owner_id VARCHAR(128) NOT NULL DEFAULT 'workspace';

CREATE INDEX IF NOT EXISTS ix_projects_owner_id
    ON public.projects (owner_id);
