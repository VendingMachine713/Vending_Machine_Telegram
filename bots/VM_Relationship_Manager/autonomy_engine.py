from __future__ import annotations

from database import Database, utcnow


MODES = {"observe", "assist", "safe"}
DEFAULTS = {
    "autonomy_mode": "safe",
    "classification_auto_threshold": "85",
    "exception_threshold": "50",
    "daily_exception_limit": "12",
    "suppress_clear_digests": "1",
    "exception_critical_threshold": "85",
    "exception_per_contact_limit": "2",
    "dismissal_cooldown_days": "14",
    "done_cooldown_days": "2",
}


class AutonomyEngine:
    """Central policy for passive/admin-by-exception behaviour.

    'safe' performs reversible metadata maintenance and high-confidence safe
    classification only. It never sends messages to contacts or makes external
    commercial decisions.
    """

    def __init__(self, db: Database):
        self.db = db
        self.ensure_defaults()

    def ensure_defaults(self):
        for key, value in DEFAULTS.items():
            if self.db.meta(key) is None:
                self.db.set_meta(key, value)

    def mode(self):
        mode = self.db.meta("autonomy_mode", "safe")
        return mode if mode in MODES else "safe"

    def set_mode(self, mode: str, admin_id: int):
        mode = (mode or "").strip().lower()
        if mode not in MODES:
            raise ValueError("Mode must be observe, assist or safe")
        old = self.mode()
        self.db.set_meta("autonomy_mode", mode)
        self.db.execute(
            "INSERT INTO autonomy_audit(admin_id,old_mode,new_mode,details,created_at) VALUES (?,?,?,?,?)",
            (admin_id, old, mode, "Admin changed autonomy mode", utcnow()),
        )
        return mode

    def settings(self):
        self.ensure_defaults()
        return {
            "mode": self.mode(),
            "classification_auto_threshold": int(self.db.meta("classification_auto_threshold", "85")),
            "exception_threshold": int(self.db.meta("exception_threshold", "50")),
            "daily_exception_limit": int(self.db.meta("daily_exception_limit", "12")),
            "suppress_clear_digests": self.db.meta("suppress_clear_digests", "1") == "1",
            "exception_critical_threshold": int(self.db.meta("exception_critical_threshold", "85")),
            "exception_per_contact_limit": int(self.db.meta("exception_per_contact_limit", "2")),
            "dismissal_cooldown_days": int(self.db.meta("dismissal_cooldown_days", "14")),
            "done_cooldown_days": int(self.db.meta("done_cooldown_days", "2")),
        }
