-- ROLLBACK: ALTER TABLE pending_replies DROP COLUMN IF EXISTS user_id; ALTER TABLE contact_template_history DROP COLUMN IF EXISTS user_id; ALTER TABLE deal_stage_log DROP COLUMN IF EXISTS user_id; ALTER TABLE contact_products DROP COLUMN IF EXISTS user_id; ALTER TABLE conversations DROP COLUMN IF EXISTS user_id; ALTER TABLE newsletter_sends DROP COLUMN IF EXISTS user_id; ALTER TABLE newsletter_attachments DROP COLUMN IF EXISTS user_id;
-- Sprint 2A: Add user_id to 7 child tables for defense-in-depth multi-tenancy.
-- These tables previously relied on FK-join isolation (contact_id → contacts.user_id).
-- Direct user_id enables scoped queries without JOINs and prevents cross-tenant leaks.

-- ============================================================
-- 1. pending_replies (FK: contact_id → contacts)
-- ============================================================
ALTER TABLE pending_replies ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
UPDATE pending_replies pr
   SET user_id = COALESCE(
       (SELECT c.user_id FROM contacts c WHERE c.id = pr.contact_id),
       1
   )
 WHERE pr.user_id IS NULL;
ALTER TABLE pending_replies ALTER COLUMN user_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_pending_replies_user ON pending_replies(user_id);

-- ============================================================
-- 2. contact_template_history (FK: contact_id → contacts)
-- ============================================================
ALTER TABLE contact_template_history ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
UPDATE contact_template_history cth
   SET user_id = COALESCE(
       (SELECT c.user_id FROM contacts c WHERE c.id = cth.contact_id),
       1
   )
 WHERE cth.user_id IS NULL;
ALTER TABLE contact_template_history ALTER COLUMN user_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cth_user ON contact_template_history(user_id);

-- ============================================================
-- 3. deal_stage_log (FK: deal_id → deals, which has user_id)
-- ============================================================
ALTER TABLE deal_stage_log ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
UPDATE deal_stage_log dsl
   SET user_id = COALESCE(
       (SELECT d.user_id FROM deals d WHERE d.id = dsl.deal_id),
       1
   )
 WHERE dsl.user_id IS NULL;
ALTER TABLE deal_stage_log ALTER COLUMN user_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_deal_stage_log_user ON deal_stage_log(user_id);

-- ============================================================
-- 4. contact_products (FK: contact_id → contacts)
-- ============================================================
ALTER TABLE contact_products ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
UPDATE contact_products cp
   SET user_id = COALESCE(
       (SELECT c.user_id FROM contacts c WHERE c.id = cp.contact_id),
       1
   )
 WHERE cp.user_id IS NULL;
ALTER TABLE contact_products ALTER COLUMN user_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_contact_products_user ON contact_products(user_id);

-- ============================================================
-- 5. conversations (FK: contact_id → contacts)
-- ============================================================
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
UPDATE conversations cv
   SET user_id = COALESCE(
       (SELECT c.user_id FROM contacts c WHERE c.id = cv.contact_id),
       1
   )
 WHERE cv.user_id IS NULL;
ALTER TABLE conversations ALTER COLUMN user_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);

-- ============================================================
-- 6. newsletter_sends (FK: newsletter_id → newsletters)
-- ============================================================
ALTER TABLE newsletter_sends ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
UPDATE newsletter_sends ns
   SET user_id = COALESCE(
       (SELECT n.user_id FROM newsletters n WHERE n.id = ns.newsletter_id),
       1
   )
 WHERE ns.user_id IS NULL;
ALTER TABLE newsletter_sends ALTER COLUMN user_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_newsletter_sends_user ON newsletter_sends(user_id);

-- ============================================================
-- 7. newsletter_attachments (FK: newsletter_id → newsletters)
-- ============================================================
ALTER TABLE newsletter_attachments ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
UPDATE newsletter_attachments na
   SET user_id = COALESCE(
       (SELECT n.user_id FROM newsletters n WHERE n.id = na.newsletter_id),
       1
   )
 WHERE na.user_id IS NULL;
ALTER TABLE newsletter_attachments ALTER COLUMN user_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_newsletter_attachments_user ON newsletter_attachments(user_id);

-- ============================================================
-- 8. Rebuild interaction_timeline_view with user_id column
-- Must DROP first because adding a column changes the view definition
-- ============================================================
DROP VIEW IF EXISTS interaction_timeline_view;
CREATE VIEW interaction_timeline_view AS
    -- Events (email_sent, linkedin_*, status transitions, etc.)
    SELECT
        e.contact_id,
        e.campaign_id,
        e.user_id,
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
        gd.user_id,
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
        pr.user_id,
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
        rn.user_id,
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
        cv.user_id,
        'conversation' AS source,
        cv.channel AS interaction_type,
        cv.title AS subject,
        cv.notes AS body,
        NULL::TEXT AS metadata,
        cv.occurred_at
    FROM conversations cv;
