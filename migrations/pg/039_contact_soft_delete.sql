-- ROLLBACK: ALTER TABLE contacts DROP COLUMN IF EXISTS removed_at; ALTER TABLE contacts DROP COLUMN IF EXISTS removal_reason;
-- Soft-delete for contacts: removed contacts are hidden but preserved for re-upload detection
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS removed_at TIMESTAMPTZ;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS removal_reason TEXT;
CREATE INDEX IF NOT EXISTS idx_contacts_removed ON contacts(user_id, removed_at) WHERE removed_at IS NOT NULL;
