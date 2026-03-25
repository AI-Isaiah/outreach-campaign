-- 014: Multi-tenancy — users, allowed_emails, user_id on root tables

-- 1. Users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT,
    password_hash TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Invite list
CREATE TABLE IF NOT EXISTS allowed_emails (
    email TEXT PRIMARY KEY,
    note TEXT,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Password reset tokens
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    used BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. Seed allowed emails
INSERT INTO allowed_emails (email, note) VALUES
    ('helmut.mueller1@gmail.com', 'founder')
ON CONFLICT DO NOTHING;

-- 5. Seed helmut as a user (password set on first login via forgot-password flow)
INSERT INTO users (email, name, is_active) VALUES
    ('helmut.mueller1@gmail.com', 'Helmut Mueller', true)
ON CONFLICT (email) DO NOTHING;

-- 6. Add user_id to root tables (nullable first, then backfill, then NOT NULL)
ALTER TABLE companies      ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE campaigns      ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE templates      ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE tags           ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE products       ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE newsletters    ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE research_jobs  ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;

-- 7. Backfill existing rows to helmut's user_id
DO $$
DECLARE v_uid INTEGER;
BEGIN
    SELECT id INTO v_uid FROM users WHERE email = 'helmut.mueller1@gmail.com';
    IF v_uid IS NOT NULL THEN
        UPDATE companies     SET user_id = v_uid WHERE user_id IS NULL;
        UPDATE campaigns     SET user_id = v_uid WHERE user_id IS NULL;
        UPDATE templates     SET user_id = v_uid WHERE user_id IS NULL;
        UPDATE tags          SET user_id = v_uid WHERE user_id IS NULL;
        UPDATE products      SET user_id = v_uid WHERE user_id IS NULL;
        UPDATE newsletters   SET user_id = v_uid WHERE user_id IS NULL;
        UPDATE research_jobs SET user_id = v_uid WHERE user_id IS NULL;
    END IF;
END $$;

-- 8. Make user_id NOT NULL
ALTER TABLE companies      ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE campaigns      ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE templates      ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE tags           ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE products       ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE newsletters    ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE research_jobs  ALTER COLUMN user_id SET NOT NULL;

-- 9. Fix unique constraints to be per-user
DO $$ BEGIN
    ALTER TABLE tags DROP CONSTRAINT IF EXISTS tags_name_key;
EXCEPTION WHEN undefined_object THEN NULL;
END $$;
DO $$ BEGIN
    ALTER TABLE tags ADD CONSTRAINT tags_user_name_unique UNIQUE (user_id, name);
EXCEPTION WHEN duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE products DROP CONSTRAINT IF EXISTS products_name_key;
EXCEPTION WHEN undefined_object THEN NULL;
END $$;
DO $$ BEGIN
    ALTER TABLE products ADD CONSTRAINT products_user_name_unique UNIQUE (user_id, name);
EXCEPTION WHEN duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS campaigns_name_key;
EXCEPTION WHEN undefined_object THEN NULL;
END $$;
DO $$ BEGIN
    ALTER TABLE campaigns ADD CONSTRAINT campaigns_user_name_unique UNIQUE (user_id, name);
EXCEPTION WHEN duplicate_table THEN NULL;
END $$;

-- 10. Indexes
CREATE INDEX IF NOT EXISTS idx_companies_user     ON companies(user_id);
CREATE INDEX IF NOT EXISTS idx_campaigns_user     ON campaigns(user_id);
CREATE INDEX IF NOT EXISTS idx_templates_user     ON templates(user_id);
CREATE INDEX IF NOT EXISTS idx_tags_user          ON tags(user_id);
CREATE INDEX IF NOT EXISTS idx_products_user      ON products(user_id);
CREATE INDEX IF NOT EXISTS idx_newsletters_user   ON newsletters(user_id);
CREATE INDEX IF NOT EXISTS idx_research_jobs_user ON research_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_reset_tokens_token ON password_reset_tokens(token);
