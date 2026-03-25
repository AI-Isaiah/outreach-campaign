-- Migration 006: CRM Pipeline — deals, tags, entity tagging
-- Adds deal pipeline tracking, tagging system for contacts/companies

-- Deals (company-level pipeline tracking)
CREATE TABLE IF NOT EXISTS deals (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    contact_id INTEGER REFERENCES contacts(id),
    campaign_id INTEGER REFERENCES campaigns(id),
    title TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'cold'
        CHECK (stage IN ('cold', 'contacted', 'engaged', 'meeting_booked', 'negotiating', 'won', 'lost')),
    amount_millions NUMERIC,
    expected_close_date DATE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Deal stage change log
CREATE TABLE IF NOT EXISTS deal_stage_log (
    id SERIAL PRIMARY KEY,
    deal_id INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    from_stage TEXT,
    to_stage TEXT NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Tags
CREATE TABLE IF NOT EXISTS tags (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL DEFAULT '#6B7280',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Polymorphic junction: tags ↔ contacts/companies
CREATE TABLE IF NOT EXISTS entity_tags (
    id SERIAL PRIMARY KEY,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('contact', 'company')),
    entity_id INTEGER NOT NULL,
    UNIQUE (tag_id, entity_type, entity_id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_deals_company ON deals(company_id);
CREATE INDEX IF NOT EXISTS idx_deals_stage ON deals(stage);
CREATE INDEX IF NOT EXISTS idx_deals_contact ON deals(contact_id);
CREATE INDEX IF NOT EXISTS idx_deal_stage_log_deal ON deal_stage_log(deal_id);
CREATE INDEX IF NOT EXISTS idx_entity_tags_entity ON entity_tags(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_tags_tag ON entity_tags(tag_id);
