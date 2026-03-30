-- ROLLBACK: ALTER TABLE gdpr_deletion_log ADD COLUMN IF NOT EXISTS contact_name TEXT;
-- Remove PII from GDPR deletion audit log. Contact name is personal data
-- that should not be retained after a GDPR deletion request.
ALTER TABLE gdpr_deletion_log DROP COLUMN IF EXISTS contact_name;
