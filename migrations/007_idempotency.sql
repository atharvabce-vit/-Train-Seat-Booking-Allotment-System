-- Idempotency keys so a retried booking or charge is not duplicated.
ALTER TABLE bookings ADD COLUMN idempotency_key TEXT;
ALTER TABLE payments ADD COLUMN idempotency_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_bookings_idem ON bookings(idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_idem ON payments(idempotency_key)
    WHERE idempotency_key IS NOT NULL;
