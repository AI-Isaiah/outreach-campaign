-- 017: Full multi-tenancy — data isolation + Gmail OAuth + SMTP + compliance

-- 1. Gmail OAuth columns on users
ALTER TABLE users ADD COLUMN IF NOT EXISTS gmail_access_token TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS gmail_refresh_token TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS gmail_token_expiry TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS gmail_connected BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS gmail_email TEXT;

-- 2. Optional SMTP fallback columns on users
ALTER TABLE users ADD COLUMN IF NOT EXISTS smtp_host TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS smtp_port INTEGER;
ALTER TABLE users ADD COLUMN IF NOT EXISTS smtp_username TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS smtp_password TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS smtp_use_tls BOOLEAN DEFAULT true;
ALTER TABLE users ADD COLUMN IF NOT EXISTS smtp_from_email TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS smtp_from_name TEXT;

-- 3. Per-user compliance columns on users
ALTER TABLE users ADD COLUMN IF NOT EXISTS physical_address TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS calendly_url TEXT;

-- 4. contacts: add direct user_id (currently only via company FK)
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
UPDATE contacts SET user_id = c.user_id FROM companies c WHERE contacts.company_id = c.id AND contacts.user_id IS NULL;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='contacts' AND column_name='user_id' AND is_nullable='YES') THEN
        ALTER TABLE contacts ALTER COLUMN user_id SET NOT NULL;
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_contacts_user ON contacts(user_id);

-- 5. engine_config: add user_id for per-user engine settings
-- Note: engine_config was truly global before this migration, so all rows belong to the founder.
ALTER TABLE engine_config ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
DO $$
DECLARE v_uid INTEGER;
BEGIN
    SELECT id INTO v_uid FROM users WHERE email = 'founder@example.com';
    IF v_uid IS NOT NULL THEN
        UPDATE engine_config SET user_id = v_uid WHERE user_id IS NULL;
    END IF;
END $$;
-- Add surrogate PK and per-user unique constraint
ALTER TABLE engine_config ADD COLUMN IF NOT EXISTS id SERIAL;
DO $$ BEGIN
    ALTER TABLE engine_config DROP CONSTRAINT IF EXISTS engine_config_pkey;
EXCEPTION WHEN undefined_object THEN NULL;
END $$;
DO $$ BEGIN
    ALTER TABLE engine_config ADD PRIMARY KEY (id);
EXCEPTION WHEN duplicate_table THEN NULL;
END $$;
DO $$ BEGIN
    ALTER TABLE engine_config ADD CONSTRAINT engine_config_user_key_unique UNIQUE (user_id, key);
EXCEPTION WHEN duplicate_table THEN NULL;
END $$;

-- 6. events: add user_id for faster filtering
ALTER TABLE events ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
-- Backfill via campaigns table (events.campaign_id → campaigns.user_id)
DO $$
DECLARE v_uid INTEGER;
BEGIN
    UPDATE events e SET user_id = camp.user_id
        FROM campaigns camp
        WHERE e.campaign_id = camp.id AND e.user_id IS NULL;
    -- Fallback: any remaining events without campaign_id get founder's user_id
    SELECT id INTO v_uid FROM users WHERE email = 'founder@example.com';
    IF v_uid IS NOT NULL THEN
        UPDATE events SET user_id = v_uid WHERE user_id IS NULL;
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);

-- 7. dedup_log: add user_id for per-user dedup scoping
ALTER TABLE dedup_log ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
DO $$
DECLARE v_uid INTEGER;
BEGIN
    SELECT id INTO v_uid FROM users WHERE email = 'founder@example.com';
    IF v_uid IS NOT NULL THEN
        UPDATE dedup_log SET user_id = v_uid WHERE user_id IS NULL;
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_dedup_log_user ON dedup_log(user_id);

-- 8. deals: add user_id
ALTER TABLE deals ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
DO $$
DECLARE v_uid INTEGER;
BEGIN
    -- First backfill: via contact → company (for deals with contact_id)
    UPDATE deals SET user_id = c.user_id FROM contacts ct JOIN companies c ON ct.company_id = c.id WHERE deals.contact_id = ct.id AND deals.user_id IS NULL;
    -- Second backfill: via company directly
    UPDATE deals SET user_id = c.user_id FROM companies c WHERE deals.company_id = c.id AND deals.user_id IS NULL;
    -- Fallback
    SELECT id INTO v_uid FROM users WHERE email = 'founder@example.com';
    IF v_uid IS NOT NULL THEN
        UPDATE deals SET user_id = v_uid WHERE user_id IS NULL;
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_deals_user ON deals(user_id);

-- 9. Per-user unique constraints for contacts
-- contacts: email_normalized unique per user (not globally)
DROP INDEX IF EXISTS idx_contacts_email_norm;
DROP INDEX IF EXISTS idx_contacts_email_norm_unique;
CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_user_email_norm ON contacts(user_id, email_normalized) WHERE email_normalized IS NOT NULL;
-- contacts: linkedin_url_normalized unique per user
DROP INDEX IF EXISTS idx_contacts_linkedin_norm;
DROP INDEX IF EXISTS idx_contacts_linkedin_norm_unique;
CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_user_linkedin_norm ON contacts(user_id, linkedin_url_normalized) WHERE linkedin_url_normalized IS NOT NULL;

-- 10. OAuth state tokens for CSRF protection in Gmail OAuth flow
CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
