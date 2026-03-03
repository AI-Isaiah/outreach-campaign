-- Gmail draft tracking
CREATE TABLE IF NOT EXISTS gmail_drafts (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    template_id INTEGER REFERENCES templates(id) ON DELETE SET NULL,
    gmail_draft_id TEXT NOT NULL,
    subject TEXT,
    to_email TEXT NOT NULL,
    body_text TEXT,
    body_html TEXT,
    status TEXT NOT NULL DEFAULT 'drafted',
    pushed_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gmail_drafts_contact ON gmail_drafts(contact_id);
CREATE INDEX IF NOT EXISTS idx_gmail_drafts_status ON gmail_drafts(status);

-- Response notes for manual tracking
CREATE TABLE IF NOT EXISTS response_notes (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,
    note_type TEXT NOT NULL DEFAULT 'general',
    response_type TEXT,
    content TEXT NOT NULL,
    note TEXT,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_response_notes_contact ON response_notes(contact_id);
