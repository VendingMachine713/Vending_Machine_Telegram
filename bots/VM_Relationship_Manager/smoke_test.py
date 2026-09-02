from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timezone, timedelta

from database import Database
from relationship_engine import RelationshipEngine


with TemporaryDirectory() as td:
    db = Database(Path(td) / "test.db")
    engine = RelationshipEngine(db)

    now = datetime.now(timezone.utc)

    # Historical/direct identity discovery must not invent interactions.
    engine.upsert_identity(
        telegram_id=123456789,
        username="testuser",
        display_name="Test User",
        observed_at=now - timedelta(days=7),
        chat_id=-100123,
        chat_title="Test Group",
        source="smoke_seed",
    )

    seeded = db.one("SELECT * FROM contacts WHERE telegram_id=?", (123456789,))
    assert seeded is not None
    assert seeded["interaction_count"] == 0
    assert seeded["active_days"] == 0

    # First real live interaction should create the first active day.
    engine.upsert_interaction(
        telegram_id=123456789,
        username="testuser",
        display_name="Test User",
        chat_id=-100123,
        chat_title="Test Group",
        occurred_at=now,
    )
    engine.add_tag(123456789, "regular")
    engine.set_relationship_type(123456789, "regular", 999)
    engine.set_verification(123456789, "verified", 999, "Smoke test")
    engine.recalculate_contact(123456789)

    c = db.one("SELECT * FROM contacts WHERE telegram_id=?", (123456789,))
    assert c["relationship_type"] == "regular"
    assert c["verification_status"] == "verified"
    assert c["interaction_count"] == 1
    assert c["active_days"] == 1
    assert c["relationship_score"] > 0
    assert c["trust_score"] >= 70

    intel = engine.get_intelligence(123456789)
    assert intel is not None
    assert 0 <= intel["health_score"] <= 100
    assert intel["momentum_label"] in {"learning", "stable", "growing", "surging", "cooling", "fading"}
    assert intel["lifecycle_stage"] in {
        "discovered", "new", "developing", "established", "strong",
        "vip_candidate", "vip", "cooling", "dormant", "returned",
    }
    snapshot = db.one(
        "SELECT * FROM relationship_snapshots WHERE telegram_id=?", (123456789,)
    )
    assert snapshot is not None

    print("SMOKE TEST PASSED")
    print(dict(c))
