"""Match Engine v2 checkpoint migration.

Adds durable marketplace-change events, WTB expiry/reminder state, and the
outbound reminder queue. Existing v1.5 match/feedback tables remain canonical.
All statements are idempotent and safe to run on every startup.
"""

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS marketplace_match_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id INTEGER,
  previous_logical_listing_id TEXT,
  logical_listing_id TEXT,
  event_kind TEXT NOT NULL,
  created_utc TEXT NOT NULL,
  processed_utc TEXT
);
CREATE INDEX IF NOT EXISTS ix_market_match_events_pending
  ON marketplace_match_events(processed_utc,id);
CREATE INDEX IF NOT EXISTS ix_market_match_events_logical
  ON marketplace_match_events(logical_listing_id,processed_utc);

CREATE TABLE IF NOT EXISTS marketplace_wtb_expiry(
  demand_logical_id TEXT PRIMARY KEY,
  listing_id INTEGER NOT NULL,
  first_seen_utc TEXT NOT NULL,
  remind_utc TEXT NOT NULL,
  expires_utc TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'scheduled',
  reminded_utc TEXT,
  created_utc TEXT NOT NULL,
  updated_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_market_wtb_expiry_due
  ON marketplace_wtb_expiry(status,remind_utc);

CREATE TABLE IF NOT EXISTS marketplace_wtb_expiry_alert_queue(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  demand_logical_id TEXT NOT NULL,
  owner_user_id INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  due_utc TEXT NOT NULL,
  created_utc TEXT NOT NULL,
  sent_utc TEXT,
  last_error TEXT,
  UNIQUE(demand_logical_id,owner_user_id)
);
CREATE INDEX IF NOT EXISTS ix_market_wtb_expiry_alert_due
  ON marketplace_wtb_expiry_alert_queue(status,due_utc);

CREATE TABLE IF NOT EXISTS marketplace_match_v2_state(
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_utc TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS marketplace_match_event_ai
AFTER INSERT ON marketplace_listings
BEGIN
  INSERT INTO marketplace_match_events(
    listing_id,previous_logical_listing_id,logical_listing_id,event_kind,created_utc
  ) VALUES(
    new.id,NULL,new.logical_listing_id,'insert',strftime('%Y-%m-%dT%H:%M:%fZ','now')
  );
END;

CREATE TRIGGER IF NOT EXISTS marketplace_match_event_au
AFTER UPDATE OF
  sender_id,listing_type,title,category,price_cents,currency,condition,
  location_hint,status,confidence,logical_listing_id,fingerprint
ON marketplace_listings
WHEN
  old.sender_id IS NOT new.sender_id OR
  old.listing_type IS NOT new.listing_type OR
  old.title IS NOT new.title OR
  old.category IS NOT new.category OR
  old.price_cents IS NOT new.price_cents OR
  old.currency IS NOT new.currency OR
  old.condition IS NOT new.condition OR
  old.location_hint IS NOT new.location_hint OR
  old.status IS NOT new.status OR
  old.confidence IS NOT new.confidence OR
  old.logical_listing_id IS NOT new.logical_listing_id OR
  old.fingerprint IS NOT new.fingerprint
BEGIN
  INSERT INTO marketplace_match_events(
    listing_id,previous_logical_listing_id,logical_listing_id,event_kind,created_utc
  ) VALUES(
    new.id,old.logical_listing_id,new.logical_listing_id,'update',strftime('%Y-%m-%dT%H:%M:%fZ','now')
  );
END;

CREATE TRIGGER IF NOT EXISTS marketplace_match_event_bd
BEFORE DELETE ON marketplace_listings
BEGIN
  INSERT INTO marketplace_match_events(
    listing_id,previous_logical_listing_id,logical_listing_id,event_kind,created_utc
  ) VALUES(
    old.id,old.logical_listing_id,NULL,'delete',strftime('%Y-%m-%dT%H:%M:%fZ','now')
  );
END;
"""


def upgrade(conn):
    conn.executescript(SCHEMA)
