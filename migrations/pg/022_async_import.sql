-- Async import: add analyzing status, analysis result storage, and filename
-- Allows import analysis to run in background while user navigates away

-- Store the full LLM analysis result so frontend can reconstruct state on resume
ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS analysis_result JSONB;

-- Store original filename for display in notifications/resume UI
ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS filename TEXT;

-- Expand status to include 'analyzing' (LLM running in background)
-- and 'failed' (analysis error).  PostgreSQL doesn't support ALTER CHECK
-- directly, so drop-and-recreate if the constraint exists.
DO $$
BEGIN
    -- Drop old constraint if it exists (may not exist if no CHECK was defined)
    ALTER TABLE import_jobs DROP CONSTRAINT IF EXISTS import_jobs_status_check;
EXCEPTION WHEN undefined_object THEN
    NULL;
END $$;

ALTER TABLE import_jobs ADD CONSTRAINT import_jobs_status_check
    CHECK (status IN ('analyzing', 'pending', 'previewed', 'completed', 'failed'));
