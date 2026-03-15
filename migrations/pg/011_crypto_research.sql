-- Migration 011: Crypto Interest Research Pipeline
-- Batch research jobs and per-company results with scoring

-- Research jobs (batch tracking)
CREATE TABLE IF NOT EXISTS research_jobs (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'researching', 'classifying', 'completed', 'failed')),
    method TEXT NOT NULL DEFAULT 'hybrid'
        CHECK (method IN ('web_search', 'website_crawl', 'hybrid')),
    total_companies INTEGER NOT NULL DEFAULT 0,
    processed_companies INTEGER NOT NULL DEFAULT 0,
    classified_companies INTEGER NOT NULL DEFAULT 0,
    contacts_discovered INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    cost_estimate_usd REAL,
    actual_cost_usd REAL NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Per-company research results
CREATE TABLE IF NOT EXISTS research_results (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES research_jobs(id) ON DELETE CASCADE,
    company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    company_name TEXT NOT NULL,
    company_website TEXT,
    web_search_raw TEXT,
    website_crawl_raw TEXT,
    crypto_score INTEGER,
    category TEXT
        CHECK (category IN ('confirmed_investor', 'likely_interested', 'possible', 'no_signal', 'unlikely')),
    evidence_summary TEXT,
    evidence_json JSONB,
    classification_reasoning TEXT,
    discovered_contacts_json JSONB,
    warm_intro_contact_ids INTEGER[],
    warm_intro_notes TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'researching', 'classified', 'completed', 'error')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_research_results_job ON research_results(job_id);
CREATE INDEX IF NOT EXISTS idx_research_results_category ON research_results(category);
CREATE INDEX IF NOT EXISTS idx_research_results_score ON research_results(crypto_score DESC);
CREATE INDEX IF NOT EXISTS idx_research_results_company ON research_results(company_id);
CREATE INDEX IF NOT EXISTS idx_research_jobs_status ON research_jobs(status);
