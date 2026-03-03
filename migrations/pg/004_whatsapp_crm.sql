-- Phone number support on contacts
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS phone_number TEXT;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS phone_normalized TEXT;

CREATE INDEX IF NOT EXISTS idx_contacts_phone_norm ON contacts(phone_normalized);
CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_phone_unique ON contacts(phone_normalized)
    WHERE phone_normalized IS NOT NULL;

-- WhatsApp message capture
CREATE TABLE IF NOT EXISTS whatsapp_messages (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    phone_number TEXT NOT NULL,
    message_text TEXT NOT NULL,
    direction TEXT NOT NULL,
    whatsapp_timestamp TIMESTAMPTZ,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(contact_id, whatsapp_timestamp, direction, message_text)
);

CREATE INDEX IF NOT EXISTS idx_wa_messages_contact ON whatsapp_messages(contact_id);
CREATE INDEX IF NOT EXISTS idx_wa_timestamp ON whatsapp_messages(whatsapp_timestamp DESC);

-- WhatsApp scan state tracking
CREATE TABLE IF NOT EXISTS whatsapp_scan_state (
    contact_id INTEGER PRIMARY KEY REFERENCES contacts(id) ON DELETE CASCADE,
    last_scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_message_at TIMESTAMPTZ
);

-- Unified interaction timeline view
CREATE OR REPLACE VIEW interaction_timeline_view AS
    -- Events (email_sent, linkedin_*, status transitions, etc.)
    SELECT
        e.contact_id,
        e.campaign_id,
        'event' AS source,
        e.event_type AS interaction_type,
        NULL::TEXT AS subject,
        COALESCE(e.notes, '') AS body,
        e.metadata,
        e.created_at AS occurred_at
    FROM events e

    UNION ALL

    -- Gmail drafts
    SELECT
        gd.contact_id,
        gd.campaign_id,
        'gmail' AS source,
        CASE WHEN gd.status = 'sent' THEN 'email_sent' ELSE 'email_drafted' END AS interaction_type,
        gd.subject,
        gd.body_text AS body,
        NULL::TEXT AS metadata,
        COALESCE(gd.sent_at, gd.pushed_at, gd.created_at) AS occurred_at
    FROM gmail_drafts gd

    UNION ALL

    -- Pending replies (detected from Gmail)
    SELECT
        pr.contact_id,
        pr.campaign_id,
        'reply' AS source,
        COALESCE(pr.confirmed_outcome, pr.classification, 'unknown') AS interaction_type,
        pr.subject,
        pr.snippet AS body,
        NULL::TEXT AS metadata,
        pr.detected_at AS occurred_at
    FROM pending_replies pr

    UNION ALL

    -- WhatsApp messages
    SELECT
        wm.contact_id,
        NULL::INTEGER AS campaign_id,
        'whatsapp' AS source,
        CASE WHEN wm.direction = 'outbound' THEN 'whatsapp_sent' ELSE 'whatsapp_received' END AS interaction_type,
        NULL::TEXT AS subject,
        wm.message_text AS body,
        NULL::TEXT AS metadata,
        COALESCE(wm.whatsapp_timestamp, wm.captured_at) AS occurred_at
    FROM whatsapp_messages wm

    UNION ALL

    -- Response notes
    SELECT
        rn.contact_id,
        rn.campaign_id,
        'note' AS source,
        rn.note_type AS interaction_type,
        NULL::TEXT AS subject,
        COALESCE(rn.note, rn.content) AS body,
        NULL::TEXT AS metadata,
        rn.created_at AS occurred_at
    FROM response_notes rn;
