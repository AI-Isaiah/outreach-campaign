-- Migration 007: Schema fixes — unique indexes, FK constraints, composite indexes
-- Fixes: D001 (entity_tags orphans), D002 (dedup_log FKs), D004/D005 (unique normalized),
--        D007 (timeline composite indexes)

-- D004: UNIQUE partial index on email_normalized (dedup assumes uniqueness)
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_contacts_email_norm_unique') THEN
        CREATE UNIQUE INDEX idx_contacts_email_norm_unique
        ON contacts(email_normalized)
        WHERE email_normalized IS NOT NULL;
    END IF;
END $$;

-- D005: UNIQUE partial index on linkedin_url_normalized
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_contacts_linkedin_norm_unique') THEN
        CREATE UNIQUE INDEX idx_contacts_linkedin_norm_unique
        ON contacts(linkedin_url_normalized)
        WHERE linkedin_url_normalized IS NOT NULL;
    END IF;
END $$;

-- D002: FK constraints on dedup_log (ON DELETE SET NULL to preserve audit trail)
-- First, clean up orphaned references so FK constraints can be applied
UPDATE dedup_log SET kept_contact_id = NULL
WHERE kept_contact_id IS NOT NULL
  AND kept_contact_id NOT IN (SELECT id FROM contacts);

UPDATE dedup_log SET merged_contact_id = NULL
WHERE merged_contact_id IS NOT NULL
  AND merged_contact_id NOT IN (SELECT id FROM contacts);

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_dedup_kept_contact' AND table_name = 'dedup_log'
    ) THEN
        ALTER TABLE dedup_log
            ADD CONSTRAINT fk_dedup_kept_contact
            FOREIGN KEY (kept_contact_id) REFERENCES contacts(id) ON DELETE SET NULL;
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_dedup_merged_contact' AND table_name = 'dedup_log'
    ) THEN
        ALTER TABLE dedup_log
            ADD CONSTRAINT fk_dedup_merged_contact
            FOREIGN KEY (merged_contact_id) REFERENCES contacts(id) ON DELETE SET NULL;
    END IF;
END $$;

-- D007: Composite indexes for timeline view performance
CREATE INDEX IF NOT EXISTS idx_events_contact_ts ON events(contact_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_gmail_drafts_contact_ts ON gmail_drafts(contact_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pending_replies_contact_ts ON pending_replies(contact_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_response_notes_contact_ts ON response_notes(contact_id, created_at DESC);

-- D001: Cleanup trigger for entity_tags when contacts/companies are deleted
CREATE OR REPLACE FUNCTION cleanup_entity_tags() RETURNS TRIGGER AS $$
BEGIN
    DELETE FROM entity_tags
    WHERE entity_type = TG_ARGV[0] AND entity_id = OLD.id;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_cleanup_contact_tags'
    ) THEN
        CREATE TRIGGER trg_cleanup_contact_tags
        AFTER DELETE ON contacts
        FOR EACH ROW EXECUTE FUNCTION cleanup_entity_tags('contact');
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_cleanup_company_tags'
    ) THEN
        CREATE TRIGGER trg_cleanup_company_tags
        AFTER DELETE ON companies
        FOR EACH ROW EXECUTE FUNCTION cleanup_entity_tags('company');
    END IF;
END $$;
