-- Smart CSV import: job tracking and schema templates
-- import_jobs stores parsed CSV data between API steps (analyze → preview → execute)

CREATE TABLE IF NOT EXISTS import_jobs (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'pending',
    raw_rows JSONB NOT NULL,
    headers JSONB NOT NULL,
    column_mapping JSONB,
    multi_contact_pattern JSONB,
    source_label TEXT,
    row_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- schema_templates: saved mappings for repeat imports (Phase 2, create table now)
CREATE TABLE IF NOT EXISTS schema_templates (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    fingerprint TEXT NOT NULL,
    source_label TEXT,
    column_mapping JSONB NOT NULL,
    multi_contact_pattern JSONB,
    times_used INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, fingerprint)
);
