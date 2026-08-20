CREATE TABLE customers (
  customer_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  timezone TEXT NOT NULL,
  service_plan TEXT NOT NULL
);

CREATE TABLE slots (
  slot_id TEXT PRIMARY KEY,
  service_type TEXT NOT NULL,
  day TEXT NOT NULL,
  period TEXT NOT NULL,
  capacity INTEGER NOT NULL CHECK (capacity >= 2)
);

CREATE TABLE appointments (
  appointment_id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL REFERENCES customers (customer_id),
  slot_id TEXT NOT NULL REFERENCES slots (slot_id),
  service_type TEXT NOT NULL,
  day TEXT NOT NULL,
  period TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('CONFIRMED', 'CANCELLED', 'COMPLETED')),
  version INTEGER NOT NULL,
  created_step INTEGER NOT NULL,
  cancelled_step INTEGER
);

CREATE TABLE holds (
  hold_id TEXT PRIMARY KEY,
  slot_id TEXT NOT NULL REFERENCES slots (slot_id),
  customer_id TEXT NOT NULL REFERENCES customers (customer_id),
  created_step INTEGER NOT NULL,
  ttl_steps INTEGER NOT NULL,
  released INTEGER NOT NULL CHECK (released IN (0, 1))
);

CREATE TABLE notifications (
  notification_id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL REFERENCES customers (customer_id),
  appointment_id TEXT NOT NULL REFERENCES appointments (appointment_id),
  type TEXT NOT NULL
);

CREATE TABLE operation_ledger (
  attempt_id TEXT PRIMARY KEY,
  fingerprint TEXT NOT NULL,
  tool TEXT NOT NULL,
  status TEXT NOT NULL,
  result_ref TEXT,
  step INTEGER NOT NULL
);

CREATE TABLE world_meta (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  step INTEGER NOT NULL
);
