-- Migration 009: CRM Extensions — lifecycle stages, products, conversations, newsletters

-- 1. Lifecycle stage on contacts
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS lifecycle_stage TEXT NOT NULL DEFAULT 'cold';
CREATE INDEX IF NOT EXISTS idx_contacts_lifecycle ON contacts(lifecycle_stage);

-- 2. Products table
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed default products
INSERT INTO products (name, description) VALUES
    ('Multimarket', 'Multimarket Fund'),
    ('Delta', 'Delta Fund'),
    ('Metaworld Fund', 'Metaworld Fund')
ON CONFLICT (name) DO NOTHING;

-- 3. Contact-product interest junction
CREATE TABLE IF NOT EXISTS contact_products (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    stage TEXT NOT NULL DEFAULT 'discussed',
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(contact_id, product_id)
);

CREATE INDEX IF NOT EXISTS idx_contact_products_contact ON contact_products(contact_id);
CREATE INDEX IF NOT EXISTS idx_contact_products_product ON contact_products(product_id);

-- 4. Conversations table
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    title TEXT NOT NULL,
    notes TEXT,
    outcome TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_contact ON conversations(contact_id);
CREATE INDEX IF NOT EXISTS idx_conversations_occurred ON conversations(occurred_at DESC);

-- 5. Newsletters table
CREATE TABLE IF NOT EXISTS newsletters (
    id SERIAL PRIMARY KEY,
    subject TEXT NOT NULL,
    body_html TEXT NOT NULL,
    body_text TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    sent_at TIMESTAMPTZ,
    recipient_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6. Newsletter attachments
CREATE TABLE IF NOT EXISTS newsletter_attachments (
    id SERIAL PRIMARY KEY,
    newsletter_id INTEGER NOT NULL REFERENCES newsletters(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/pdf',
    file_path TEXT NOT NULL,
    file_size_bytes INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_newsletter_attachments_newsletter ON newsletter_attachments(newsletter_id);

-- 7. Newsletter sends tracking
CREATE TABLE IF NOT EXISTS newsletter_sends (
    id SERIAL PRIMARY KEY,
    newsletter_id INTEGER NOT NULL REFERENCES newsletters(id) ON DELETE CASCADE,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    sent_at TIMESTAMPTZ,
    error_message TEXT,
    UNIQUE(newsletter_id, contact_id)
);

CREATE INDEX IF NOT EXISTS idx_newsletter_sends_newsletter ON newsletter_sends(newsletter_id);
CREATE INDEX IF NOT EXISTS idx_newsletter_sends_contact ON newsletter_sends(contact_id);

-- 8. Update interaction_timeline_view to include conversations
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
    FROM response_notes rn

    UNION ALL

    -- Conversations
    SELECT
        cv.contact_id,
        NULL::INTEGER AS campaign_id,
        'conversation' AS source,
        cv.channel AS interaction_type,
        cv.title AS subject,
        cv.notes AS body,
        NULL::TEXT AS metadata,
        cv.occurred_at
    FROM conversations cv;
