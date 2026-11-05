-- Adds per-passenger concession fare and booking-level round-trip/change fields.
ALTER TABLE bookings ADD COLUMN concession_amount INTEGER NOT NULL DEFAULT 0;
ALTER TABLE bookings ADD COLUMN group_id TEXT;
ALTER TABLE bookings ADD COLUMN trip_type TEXT NOT NULL DEFAULT 'ONE_WAY';
ALTER TABLE bookings ADD COLUMN change_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE passengers ADD COLUMN concession_percent INTEGER NOT NULL DEFAULT 0;
ALTER TABLE passengers ADD COLUMN fare INTEGER NOT NULL DEFAULT 0;
