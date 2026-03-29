-- ROLLBACK: UPDATE contact_campaign_status SET current_step_id = NULL WHERE current_step_id IS NOT NULL;
-- Backfill current_step_id for enrollments that have NULL current_step_id.
-- These were created before the auto-populate fix in enroll_contact() and
-- update_contact_campaign_status(). Without current_step_id, contacts are
-- invisible to the queue (which JOINs on stable_id).

UPDATE contact_campaign_status ccs
SET current_step_id = ss.stable_id
FROM sequence_steps ss
WHERE ccs.current_step_id IS NULL
  AND ss.campaign_id = ccs.campaign_id
  AND ss.step_order = ccs.current_step;
