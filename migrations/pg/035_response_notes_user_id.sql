-- ROLLBACK: ALTER TABLE response_notes DROP COLUMN IF EXISTS user_id;
ALTER TABLE response_notes ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
UPDATE response_notes SET user_id = (SELECT user_id FROM contacts WHERE contacts.id = response_notes.contact_id) WHERE user_id IS NULL;
ALTER TABLE response_notes ALTER COLUMN user_id SET NOT NULL;
