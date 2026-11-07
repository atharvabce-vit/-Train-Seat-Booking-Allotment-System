-- Accounts: users gain a password hash and a role so they can sign in.
ALTER TABLE users ADD COLUMN password_hash TEXT;
ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'passenger';
