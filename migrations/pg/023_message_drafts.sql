-- ROLLBACK: DROP TABLE IF EXISTS message_drafts; ALTER TABLE sequence_steps DROP COLUMN IF EXISTS draft_mode; ALTER TABLE gmail_drafts DROP COLUMN IF EXISTS user_id;
-- Phase 4: Research-powered AI message drafts (on-demand)

CREATE TABLE IF NOT EXISTS message_drafts (
    id SERIAL PRIMARY KEY,
    contact_id INT NOT NULL REFERENCES contacts(id),
    campaign_id INT NOT NULL REFERENCES campaigns(id),
    step_order INT NOT NULL,
    draft_subject TEXT,
    draft_text TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'email',
    model TEXT DEFAULT 'claude-haiku-4-5-20251001',
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    edited_at TIMESTAMPTZ,
    research_id INT REFERENCES deep_research(id),
    user_id INT NOT NULL REFERENCES users(id),
    UNIQUE(contact_id, campaign_id, step_order)
);

CREATE INDEX IF NOT EXISTS idx_message_drafts_contact_campaign
    ON message_drafts(contact_id, campaign_id);

-- AI template support on sequence steps
ALTER TABLE sequence_steps
    ADD COLUMN IF NOT EXISTS draft_mode TEXT DEFAULT 'template';

-- Bundled fix: add user_id to gmail_drafts for multi-tenancy
ALTER TABLE gmail_drafts
    ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
-- Backfill existing rows to user 1 (founder's data), then enforce NOT NULL
UPDATE gmail_drafts SET user_id = 1 WHERE user_id IS NULL;
ALTER TABLE gmail_drafts ALTER COLUMN user_id SET NOT NULL;
