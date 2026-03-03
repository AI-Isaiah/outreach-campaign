CREATE TABLE IF NOT EXISTS companies (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    name_normalized TEXT NOT NULL,
    address TEXT,
    city TEXT,
    country TEXT,
    aum_millions REAL,
    firm_type TEXT,
    website TEXT,
    linkedin_url TEXT,
    is_gdpr BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS contacts (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    first_name TEXT,
    last_name TEXT,
    full_name TEXT,
    email TEXT,
    email_normalized TEXT,
    email_status TEXT DEFAULT 'unverified',
    linkedin_url TEXT,
    linkedin_url_normalized TEXT,
    title TEXT,
    priority_rank INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'csv',
    is_gdpr BOOLEAN NOT NULL DEFAULT false,
    unsubscribed BOOLEAN NOT NULL DEFAULT false,
    unsubscribed_at TIMESTAMPTZ,
    newsletter_status TEXT NOT NULL DEFAULT 'none',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS campaigns (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS templates (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    channel TEXT NOT NULL,
    subject TEXT,
    body_template TEXT NOT NULL,
    variant_group TEXT,
    variant_label TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sequence_steps (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    channel TEXT NOT NULL,
    template_id INTEGER REFERENCES templates(id) ON DELETE SET NULL,
    delay_days INTEGER NOT NULL DEFAULT 0,
    gdpr_only BOOLEAN NOT NULL DEFAULT false,
    non_gdpr_only BOOLEAN NOT NULL DEFAULT false,
    UNIQUE(campaign_id, step_order)
);

CREATE TABLE IF NOT EXISTS contact_campaign_status (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    current_step INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'queued',
    assigned_variant TEXT,
    next_action_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(contact_id, campaign_id)
);

CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    template_id INTEGER REFERENCES templates(id) ON DELETE SET NULL,
    metadata TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dedup_log (
    id SERIAL PRIMARY KEY,
    kept_contact_id INTEGER,
    merged_contact_id INTEGER,
    match_type TEXT NOT NULL,
    match_score REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts(company_id);
CREATE INDEX IF NOT EXISTS idx_contacts_email_norm ON contacts(email_normalized);
CREATE INDEX IF NOT EXISTS idx_contacts_linkedin_norm ON contacts(linkedin_url_normalized);
CREATE INDEX IF NOT EXISTS idx_contacts_email_status ON contacts(email_status);
CREATE INDEX IF NOT EXISTS idx_ccs_status ON contact_campaign_status(status);
CREATE INDEX IF NOT EXISTS idx_ccs_campaign ON contact_campaign_status(campaign_id);
CREATE INDEX IF NOT EXISTS idx_ccs_next_action ON contact_campaign_status(next_action_date);
CREATE INDEX IF NOT EXISTS idx_events_contact ON events(contact_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_contact_campaign ON events(contact_id, campaign_id);
CREATE INDEX IF NOT EXISTS idx_contacts_company_priority ON contacts(company_id, priority_rank);
CREATE INDEX IF NOT EXISTS idx_companies_name_norm ON companies(name_normalized);
CREATE INDEX IF NOT EXISTS idx_companies_country ON companies(country);
