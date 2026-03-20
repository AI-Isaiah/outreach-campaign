-- 015: Per-user API key storage for research pipeline
ALTER TABLE users ADD COLUMN IF NOT EXISTS anthropic_api_key TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS perplexity_api_key TEXT;
