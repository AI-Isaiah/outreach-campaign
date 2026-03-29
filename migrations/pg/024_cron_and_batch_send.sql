-- ROLLBACK: ALTER TABLE users DROP COLUMN IF EXISTS last_reply_scan_at; ALTER TABLE users DROP COLUMN IF EXISTS last_scan_cursor; ALTER TABLE contact_campaign_status DROP COLUMN IF EXISTS sent_at; ALTER TABLE contact_campaign_status DROP COLUMN IF EXISTS approved_at; ALTER TABLE contact_campaign_status DROP COLUMN IF EXISTS scheduled_for;
-- Cron tracking columns on users
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_reply_scan_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_scan_cursor INT DEFAULT 0;

-- Batch send + idempotency columns on contact_campaign_status
ALTER TABLE contact_campaign_status ADD COLUMN IF NOT EXISTS sent_at TIMESTAMPTZ;
ALTER TABLE contact_campaign_status ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;
ALTER TABLE contact_campaign_status ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMPTZ;
