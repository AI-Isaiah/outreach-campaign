-- ROLLBACK: Re-run migrations/pg/004_whatsapp_crm.sql to recreate tables.
DROP TABLE IF EXISTS whatsapp_messages CASCADE;
DROP TABLE IF EXISTS whatsapp_scan_state CASCADE;

-- Recreate interaction_timeline_view without the WhatsApp UNION arm.
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
