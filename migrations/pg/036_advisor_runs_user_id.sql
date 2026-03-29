-- Add user_id to advisor_runs for multi-tenancy isolation
ALTER TABLE advisor_runs ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);

-- Backfill from campaigns
UPDATE advisor_runs ar
SET user_id = c.user_id
FROM campaigns c
WHERE ar.campaign_id = c.id
  AND ar.user_id IS NULL;

-- Make NOT NULL after backfill
ALTER TABLE advisor_runs ALTER COLUMN user_id SET NOT NULL;

-- Index for user-scoped queries
CREATE INDEX IF NOT EXISTS idx_advisor_runs_user_id ON advisor_runs(user_id);
