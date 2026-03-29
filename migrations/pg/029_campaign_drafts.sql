-- ROLLBACK: DROP TABLE IF EXISTS campaign_drafts;
-- Campaign wizard draft persistence
-- Stores in-progress campaign wizard state so users can resume later.
-- Drafts auto-expire after 30 days via expires_at.

CREATE TABLE IF NOT EXISTS campaign_drafts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name VARCHAR(200),
    form_data JSONB NOT NULL DEFAULT '{}',
    current_step INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '30 days'
);

CREATE INDEX IF NOT EXISTS idx_campaign_drafts_user ON campaign_drafts(user_id);
CREATE INDEX IF NOT EXISTS idx_campaign_drafts_expiry ON campaign_drafts(user_id, expires_at);
