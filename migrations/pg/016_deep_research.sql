-- Deep research: per-company structured research pipeline
-- Uses targeted Perplexity queries + Claude Sonnet synthesis

CREATE TABLE IF NOT EXISTS deep_research (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','researching','synthesizing','completed','failed','cancelled')),

    -- Raw research data (for debugging/re-synthesis)
    raw_queries JSONB,           -- [{query, response, cost_usd, duration_ms}]

    -- Structured output (from Sonnet synthesis)
    company_overview TEXT,
    crypto_signals JSONB,        -- [{source, quote, relevance}]
    key_people JSONB,            -- [{name, title, linkedin_url, context}]
    talking_points JSONB,        -- [{hook_type, text, source_reference}]
    risk_factors TEXT,
    updated_crypto_score INTEGER CHECK (updated_crypto_score BETWEEN 0 AND 100),
    confidence TEXT CHECK (confidence IN ('high','medium','low')),

    -- Cost tracking (REAL for consistency with research_jobs table)
    cost_estimate_usd REAL,
    actual_cost_usd REAL DEFAULT 0,
    query_count INTEGER DEFAULT 0,

    -- Metadata
    previous_crypto_score INTEGER,  -- snapshot from latest research_result before deep research
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_deep_research_company ON deep_research(company_id);
CREATE INDEX IF NOT EXISTS idx_deep_research_user ON deep_research(user_id);
CREATE INDEX IF NOT EXISTS idx_deep_research_status ON deep_research(status);

-- Only one active deep research per company per user at a time
CREATE UNIQUE INDEX IF NOT EXISTS idx_deep_research_active
    ON deep_research(company_id, user_id)
    WHERE status IN ('pending', 'researching', 'synthesizing');
