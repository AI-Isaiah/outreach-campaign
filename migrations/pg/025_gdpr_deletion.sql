-- ROLLBACK: DROP TABLE IF EXISTS gdpr_deletion_log;
-- GDPR deletion audit log
-- Stores a SHA-256 hash of deleted contact emails (no PII retained)
CREATE TABLE IF NOT EXISTS gdpr_deletion_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    contact_email_hash TEXT NOT NULL,
    contact_name TEXT,
    deleted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gdpr_deletion_log_user
    ON gdpr_deletion_log(user_id);
