-- ROLLBACK: No schema changes to reverse (documentation only).
-- 028: Document FK ON DELETE behavior (no schema changes)
--
-- events.campaign_id            → ON DELETE SET NULL  (audit logs survive campaign deletion)
-- contact_campaign_status.campaign_id → ON DELETE CASCADE  (enrollment removed with campaign)
--
-- This asymmetry is intentional: events are an immutable audit trail,
-- while enrollment status is owned by the campaign lifecycle.
-- Do NOT change events FK to CASCADE — it would destroy audit history.

SELECT 1;
