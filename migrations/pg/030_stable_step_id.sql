-- Migration 030: Add stable_id to sequence_steps and current_step_id to contact_campaign_status
-- Purpose: Enable safe step reordering without corrupting contact-to-step linkage.
-- Before: contact_campaign_status.current_step (INTEGER) JOINs on sequence_steps.step_order.
--         Reordering step_order breaks all contact references.
-- After:  contact_campaign_status.current_step_id (UUID) JOINs on sequence_steps.stable_id.
--         stable_id never changes. step_order is only for display order.

-- Step 1: Add stable_id UUID to sequence_steps
ALTER TABLE sequence_steps
  ADD COLUMN IF NOT EXISTS stable_id UUID DEFAULT gen_random_uuid();
UPDATE sequence_steps SET stable_id = gen_random_uuid() WHERE stable_id IS NULL;
ALTER TABLE sequence_steps ALTER COLUMN stable_id SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_sequence_steps_stable_id
  ON sequence_steps(stable_id);

-- Step 2: Add current_step_id UUID to contact_campaign_status
ALTER TABLE contact_campaign_status
  ADD COLUMN IF NOT EXISTS current_step_id UUID;
CREATE INDEX IF NOT EXISTS idx_ccs_current_step_id
  ON contact_campaign_status(current_step_id);

-- Step 3: Backfill current_step_id from current_step + step_order
UPDATE contact_campaign_status ccs
SET current_step_id = ss.stable_id
FROM sequence_steps ss
WHERE ss.campaign_id = ccs.campaign_id
  AND ss.step_order = ccs.current_step
  AND ccs.current_step_id IS NULL;

-- Step 4: FK constraint using NOT VALID + VALIDATE (avoids full table lock)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_ccs_current_step_id'
  ) THEN
    ALTER TABLE contact_campaign_status
      ADD CONSTRAINT fk_ccs_current_step_id
      FOREIGN KEY (current_step_id) REFERENCES sequence_steps(stable_id)
      ON DELETE SET NULL
      NOT VALID;
  END IF;
END $$;
ALTER TABLE contact_campaign_status VALIDATE CONSTRAINT fk_ccs_current_step_id;

-- Step 5: Hard-fail if active contacts have NULL current_step_id after backfill
DO $$
DECLARE
  orphan_count INTEGER;
BEGIN
  SELECT COUNT(*) INTO orphan_count
  FROM contact_campaign_status
  WHERE current_step_id IS NULL
    AND status IN ('queued', 'in_progress');
  IF orphan_count > 0 THEN
    RAISE EXCEPTION 'MIGRATION 030 FAILED: % active contacts have NULL current_step_id after backfill. Fix manually.', orphan_count;
  END IF;
END $$;

-- current_step INTEGER column kept for dual-write period. Drop in migration 031.
