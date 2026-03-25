-- Smart import ON CONFLICT constraints.
-- Companies: unique on (user_id, name_normalized) for upsert.
CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_user_name_norm
    ON companies(user_id, name_normalized);

-- Contacts: drop the partial unique index on (user_id, email_normalized)
-- and recreate as a non-partial index so ON CONFLICT (user_id, email_normalized)
-- works without a WHERE clause. The WHERE filter is unnecessary since
-- email_normalized is NULL when email is absent — NULL doesn't violate unique.
DROP INDEX IF EXISTS idx_contacts_user_email_norm;
CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_user_email_norm
    ON contacts(user_id, email_normalized);
