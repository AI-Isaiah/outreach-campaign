-- Additional performance indexes identified in codebase audit
CREATE INDEX IF NOT EXISTS idx_pending_replies_confirmed ON pending_replies(confirmed);
CREATE INDEX IF NOT EXISTS idx_pending_replies_contact ON pending_replies(contact_id);
CREATE INDEX IF NOT EXISTS idx_response_notes_contact_campaign ON response_notes(contact_id, campaign_id);
CREATE INDEX IF NOT EXISTS idx_templates_active_channel ON templates(is_active, channel);
CREATE INDEX IF NOT EXISTS idx_events_type_created ON events(event_type, created_at);
CREATE INDEX IF NOT EXISTS idx_whatsapp_messages_direction ON whatsapp_messages(direction) WHERE direction IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_dedup_log_kept ON dedup_log(kept_contact_id);
CREATE INDEX IF NOT EXISTS idx_dedup_log_merged ON dedup_log(merged_contact_id);
