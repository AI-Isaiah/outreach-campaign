-- ROLLBACK: DROP INDEX IF EXISTS idx_ccs_campaign_status;
-- 033: Add composite index for campaign+status lookups on contact_campaign_status
-- idx_events_campaign_type already exists (027_composite_indexes.sql)

CREATE INDEX IF NOT EXISTS idx_ccs_campaign_status
    ON contact_campaign_status(campaign_id, status);
