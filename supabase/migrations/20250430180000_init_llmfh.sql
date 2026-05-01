-- LLM From Here: SupaSet / SupaQueue backing tables (see src/llm_from_here/supaSet.py, supaQueue.py).
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS public.supasets (
    id SERIAL PRIMARY KEY,
    value TEXT NOT NULL,
    set_name TEXT NOT NULL,
    session_id UUID NOT NULL,
    is_session_complete BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_supasets_unique_value
    ON public.supasets (value, set_name);

CREATE TABLE IF NOT EXISTS public.supaqueue (
    id SERIAL PRIMARY KEY,
    value TEXT NOT NULL,
    queue_name TEXT NOT NULL,
    to_be_deleted BOOLEAN DEFAULT FALSE NOT NULL
);
