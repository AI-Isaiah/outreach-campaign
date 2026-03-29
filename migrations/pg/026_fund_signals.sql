-- ROLLBACK: ALTER TABLE deep_research DROP COLUMN IF EXISTS fund_signals;
ALTER TABLE deep_research ADD COLUMN IF NOT EXISTS fund_signals JSONB;
