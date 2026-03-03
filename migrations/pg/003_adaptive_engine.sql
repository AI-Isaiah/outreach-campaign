-- Track which template was used for which contact (for adaptive engine)
CREATE TABLE IF NOT EXISTS contact_template_history (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    template_id INTEGER NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    selection_mode TEXT DEFAULT 'exploit',
    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    outcome TEXT,
    outcome_at TIMESTAMPTZ,
    UNIQUE(contact_id, campaign_id, template_id)
);

CREATE INDEX IF NOT EXISTS idx_cth_contact ON contact_template_history(contact_id);
CREATE INDEX IF NOT EXISTS idx_cth_template ON contact_template_history(template_id);
CREATE INDEX IF NOT EXISTS idx_cth_outcome ON contact_template_history(outcome);

-- LLM advisor run history
CREATE TABLE IF NOT EXISTS advisor_runs (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    run_type TEXT NOT NULL DEFAULT 'analysis',
    prompt_summary TEXT,
    response_text TEXT,
    insights_json JSONB,
    template_suggestions_json JSONB,
    events_analyzed INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_advisor_runs_campaign ON advisor_runs(campaign_id);

-- Pending replies detected from Gmail
CREATE TABLE IF NOT EXISTS pending_replies (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,
    gmail_thread_id TEXT,
    gmail_message_id TEXT UNIQUE,
    reply_text TEXT,
    reply_snippet TEXT,
    subject TEXT,
    snippet TEXT,
    llm_classification TEXT,
    llm_confidence REAL,
    llm_summary TEXT,
    classification TEXT,
    confidence REAL,
    operator_classification TEXT,
    confirmed BOOLEAN NOT NULL DEFAULT false,
    confirmed_outcome TEXT,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_pending_replies_contact ON pending_replies(contact_id);
CREATE INDEX IF NOT EXISTS idx_pending_replies_unconfirmed ON pending_replies(operator_classification) WHERE operator_classification IS NULL;

-- Engine configuration (key-value store)
CREATE TABLE IF NOT EXISTS engine_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Expand gmail_drafts with additional columns for adaptive engine (idempotent)
ALTER TABLE gmail_drafts ADD COLUMN IF NOT EXISTS template_id INTEGER REFERENCES templates(id);
ALTER TABLE gmail_drafts ADD COLUMN IF NOT EXISTS body_text TEXT;
ALTER TABLE gmail_drafts ADD COLUMN IF NOT EXISTS body_html TEXT;
ALTER TABLE gmail_drafts ADD COLUMN IF NOT EXISTS pushed_at TIMESTAMPTZ;
ALTER TABLE gmail_drafts ADD COLUMN IF NOT EXISTS sent_at TIMESTAMPTZ;

-- Add CHECK constraint for selection_mode
DO $$ BEGIN
    ALTER TABLE contact_template_history
    ADD CONSTRAINT valid_selection_mode
    CHECK (selection_mode IN ('exploit', 'explore', 'manual_override', 'cold_start'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
