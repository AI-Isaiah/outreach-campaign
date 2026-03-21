-- 013: Add CHECK constraints and composite indexes for data integrity

-- CHECK constraint on contact_campaign_status.status
DO $$ BEGIN
    ALTER TABLE contact_campaign_status
        ADD CONSTRAINT chk_ccs_status
        CHECK (status IN ('queued', 'in_progress', 'replied_positive',
                          'replied_negative', 'no_response', 'bounced'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- CHECK constraint on contacts.email_status
DO $$ BEGIN
    ALTER TABLE contacts
        ADD CONSTRAINT chk_email_status
        CHECK (email_status IN ('unverified', 'valid', 'invalid', 'catch-all', 'risky', 'unknown'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Composite index for priority queue queries
CREATE INDEX IF NOT EXISTS idx_ccs_queue_lookup
    ON contact_campaign_status (campaign_id, status, next_action_date);

-- Composite index for event queries by campaign + type
CREATE INDEX IF NOT EXISTS idx_events_campaign_type
    ON events (campaign_id, event_type);

-- Index for dedup log lookups
CREATE INDEX IF NOT EXISTS idx_dedup_log_kept
    ON dedup_log (kept_contact_id);
