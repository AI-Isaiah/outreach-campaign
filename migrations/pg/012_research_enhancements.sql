-- Migration 012: Research pipeline enhancements
-- Adds cancellation support and relaxes status constraints

-- Allow cancelling/cancelled status on research jobs
DO $$ BEGIN
    ALTER TABLE research_jobs DROP CONSTRAINT IF EXISTS research_jobs_status_check;
    ALTER TABLE research_jobs ADD CONSTRAINT research_jobs_status_check
        CHECK (status IN ('pending', 'researching', 'classifying', 'completed', 'failed', 'cancelling', 'cancelled'));
EXCEPTION WHEN OTHERS THEN
    NULL;
END $$;
