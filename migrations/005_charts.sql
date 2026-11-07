-- Chart preparation: a row per train/date whose chart has been finalised.
CREATE TABLE IF NOT EXISTS charts (
    train_id    INTEGER NOT NULL REFERENCES trains(id) ON DELETE CASCADE,
    travel_date TEXT    NOT NULL,
    prepared_at TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (train_id, travel_date)
);
