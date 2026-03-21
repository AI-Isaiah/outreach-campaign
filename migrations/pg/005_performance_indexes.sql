-- Performance indexes for CRM queries, queue lookups, and reporting.

-- Composite index for priority queue CTE (campaign + status + next_action_date)
CREATE INDEX IF NOT EXISTS idx_ccs_queue_lookup
    ON contact_campaign_status(campaign_id, status, next_action_date);

-- Events: campaign + created_at for weekly summary queries
CREATE INDEX IF NOT EXISTS idx_events_campaign_created
    ON events(campaign_id, created_at);

-- Events: created_at for timeline last_activity subqueries
CREATE INDEX IF NOT EXISTS idx_events_created_at
    ON events(created_at);

-- Companies: AUM for ORDER BY in CRM list views
CREATE INDEX IF NOT EXISTS idx_companies_aum
    ON companies(aum_millions DESC NULLS LAST);

-- Contact template history: campaign for aggregate COUNT queries
CREATE INDEX IF NOT EXISTS idx_cth_campaign
    ON contact_template_history(campaign_id);

-- CCS: assigned_variant for variant comparison queries
CREATE INDEX IF NOT EXISTS idx_ccs_variant
    ON contact_campaign_status(campaign_id, assigned_variant)
    WHERE assigned_variant IS NOT NULL;

-- Contacts: full_name for ILIKE search (pg_trgm extension would be ideal
-- but CREATE EXTENSION requires superuser; a btree index still helps)
CREATE INDEX IF NOT EXISTS idx_contacts_fullname
    ON contacts(full_name);
