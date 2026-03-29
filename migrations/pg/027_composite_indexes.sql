-- ROLLBACK: DROP INDEX IF EXISTS idx_ccs_queue_lookup; DROP INDEX IF EXISTS idx_contacts_company_email; DROP INDEX IF EXISTS idx_events_campaign_type;
-- 027: Composite indexes for priority queue and reporting queries

CREATE INDEX IF NOT EXISTS idx_ccs_queue_lookup ON contact_campaign_status(campaign_id, status, next_action_date);
CREATE INDEX IF NOT EXISTS idx_contacts_company_email ON contacts(company_id, email_status);
CREATE INDEX IF NOT EXISTS idx_events_campaign_type ON events(campaign_id, event_type);
