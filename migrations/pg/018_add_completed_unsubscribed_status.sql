-- 018: Add completed and unsubscribed to contact_campaign_status CHECK constraint

DO $$ BEGIN
    ALTER TABLE contact_campaign_status DROP CONSTRAINT IF EXISTS chk_ccs_status;
    ALTER TABLE contact_campaign_status
        ADD CONSTRAINT chk_ccs_status
        CHECK (status IN ('queued', 'in_progress', 'replied_positive',
                          'replied_negative', 'no_response', 'bounced',
                          'completed', 'unsubscribed'));
END $$;
