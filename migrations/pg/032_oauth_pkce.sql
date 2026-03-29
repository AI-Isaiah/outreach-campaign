-- ROLLBACK: ALTER TABLE oauth_states DROP COLUMN IF EXISTS code_challenge;
-- PKCE binding for OAuth state tokens.
-- Stores SHA-256 hash of code_verifier to bind callback to originating browser.
ALTER TABLE oauth_states ADD COLUMN IF NOT EXISTS code_challenge TEXT;
