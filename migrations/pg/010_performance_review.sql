-- Migration 010: Performance review — indexes, FK cascades

-- 1C. Performance indexes
CREATE INDEX IF NOT EXISTS idx_events_contact_created ON events(contact_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_newsletter_sends_status ON newsletter_sends(newsletter_id, status);
CREATE INDEX IF NOT EXISTS idx_contacts_newsletter_lifecycle ON contacts(newsletter_status, lifecycle_stage);

-- Partial unique index on email_normalized (prevents duplicate emails)
CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_email_norm_unique
    ON contacts(email_normalized) WHERE email_normalized IS NOT NULL;

-- 2B. ON DELETE cascades for deals foreign keys
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE constraint_name = 'deals_company_id_fkey') THEN
        ALTER TABLE deals DROP CONSTRAINT deals_company_id_fkey;
    END IF;
END $$;
ALTER TABLE deals ADD CONSTRAINT deals_company_id_fkey
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE constraint_name = 'deals_contact_id_fkey') THEN
        ALTER TABLE deals DROP CONSTRAINT deals_contact_id_fkey;
    END IF;
END $$;
ALTER TABLE deals ADD CONSTRAINT deals_contact_id_fkey
    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE SET NULL;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE constraint_name = 'deals_campaign_id_fkey') THEN
        ALTER TABLE deals DROP CONSTRAINT deals_campaign_id_fkey;
    END IF;
END $$;
ALTER TABLE deals ADD CONSTRAINT deals_campaign_id_fkey
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE SET NULL;
