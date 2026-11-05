-- Audit trail of money/seat operations.
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    action     TEXT    NOT NULL,
    entity     TEXT    NOT NULL,
    entity_id  TEXT,
    detail     TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);

-- API tokens for the JSON REST API.
CREATE TABLE IF NOT EXISTS api_tokens (
    token         TEXT PRIMARY KEY,
    label         TEXT NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    request_count INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at  TEXT
);
