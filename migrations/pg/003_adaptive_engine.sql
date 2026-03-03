-- Track which template was used for which contact (for adaptive engine)
CREATE TABLE IF NOT EXISTS contact_template_history (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    template_id INTEGER NOT NULL REFERENCES templates(id),
    channel TEXT NOT NULL,
    sent_at TEXT NOT NULL DEFAULT NOW(),
    outcome TEXT,
    outcome_at TEXT,
    UNIQUE(contact_id, campaign_id, template_id)
);

CREATE INDEX IF NOT EXISTS idx_cth_contact ON contact_template_history(contact_id);
CREATE INDEX IF NOT EXISTS idx_cth_template ON contact_template_history(template_id);
CREATE INDEX IF NOT EXISTS idx_cth_outcome ON contact_template_history(outcome);

-- LLM advisor run history
CREATE TABLE IF NOT EXISTS advisor_runs (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    run_type TEXT NOT NULL DEFAULT 'analysis',
    prompt_summary TEXT,
    response_text TEXT,
    insights_json TEXT,
    created_at TEXT NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_advisor_runs_campaign ON advisor_runs(campaign_id);

-- Pending replies detected from Gmail
CREATE TABLE IF NOT EXISTS pending_replies (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    campaign_id INTEGER REFERENCES campaigns(id),
    gmail_thread_id TEXT,
    gmail_message_id TEXT,
    subject TEXT,
    snippet TEXT,
    classification TEXT,
    confidence REAL,
    confirmed INTEGER NOT NULL DEFAULT 0,
    confirmed_outcome TEXT,
    detected_at TEXT NOT NULL DEFAULT NOW(),
    confirmed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_pending_replies_contact ON pending_replies(contact_id);
CREATE INDEX IF NOT EXISTS idx_pending_replies_confirmed ON pending_replies(confirmed);

-- Engine configuration (key-value store)
CREATE TABLE IF NOT EXISTS engine_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT NOW()
);

-- Expand gmail_drafts with additional columns for adaptive engine
ALTER TABLE gmail_drafts ADD COLUMN IF NOT EXISTS template_id INTEGER REFERENCES templates(id);
ALTER TABLE gmail_drafts ADD COLUMN IF NOT EXISTS body_text TEXT;
ALTER TABLE gmail_drafts ADD COLUMN IF NOT EXISTS body_html TEXT;
ALTER TABLE gmail_drafts ADD COLUMN IF NOT EXISTS pushed_at TEXT;
ALTER TABLE gmail_drafts ADD COLUMN IF NOT EXISTS sent_at TEXT;
