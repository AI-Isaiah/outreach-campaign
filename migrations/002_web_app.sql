-- Gmail draft tracking
CREATE TABLE IF NOT EXISTS gmail_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    gmail_draft_id TEXT NOT NULL,
    subject TEXT,
    to_email TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'drafted',  -- drafted | sent | deleted
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_gmail_drafts_contact ON gmail_drafts(contact_id);
CREATE INDEX IF NOT EXISTS idx_gmail_drafts_status ON gmail_drafts(status);

-- Response notes for manual tracking
CREATE TABLE IF NOT EXISTS response_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    campaign_id INTEGER REFERENCES campaigns(id),
    note_type TEXT NOT NULL DEFAULT 'general',  -- general | positive_reply | negative_reply | call_booked
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_response_notes_contact ON response_notes(contact_id);
