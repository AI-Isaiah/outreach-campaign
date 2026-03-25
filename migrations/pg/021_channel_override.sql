-- 021: Add channel_override column for per-contact channel overrides.
-- Used by cross-campaign email dedup (same contact in multiple campaigns)
-- and manual channel overrides. Queue SQL reads: COALESCE(channel_override, ss.channel)

ALTER TABLE contact_campaign_status
  ADD COLUMN IF NOT EXISTS channel_override VARCHAR(20);
