from __future__ import annotations

from database import Database


PLAYBOOKS = {
    "relationship_development": [
        "Keep learning the relationship before making strong assumptions.",
        "Classify or verify only when there is enough legitimate context.",
        "Create a goal only when there is a concrete next outcome to manage.",
    ],
    "customer_nurture": [
        "Confirm the current need or outcome.",
        "Keep the next follow-up aligned with their normal contact cycle.",
        "Record any commitment as structured memory or a goal.",
    ],
    "supplier_management": [
        "Confirm availability, terms or next operational dependency.",
        "Track the next commercial action as a goal/opportunity.",
        "Review reliability/trust signals before increasing dependency.",
    ],
    "vip_nurture": [
        "Protect the relationship cadence before health drops.",
        "Capture important context/preferences as structured memory.",
        "Avoid unnecessary reminders when momentum is already healthy.",
    ],
    "dormant_revival": [
        "Check whether inactivity is genuinely outside the learned cycle.",
        "Review last known context and unresolved commitments.",
        "Create one low-pressure next step rather than repeated follow-ups.",
    ],
    "verification_review": [
        "Confirm identity/role through legitimate known context.",
        "Review pending VM risk signals.",
        "Set verification status only when evidence is sufficient.",
    ],
    "opportunity_progress": [
        "Define one concrete next action and due date.",
        "Update stage/probability after material movement.",
        "Close or pause stale opportunities instead of leaving them ambiguous.",
    ],
}


class PlaybookEngine:
    def __init__(self, db: Database):
        self.db = db

    def names(self):
        return sorted(PLAYBOOKS)

    def recommend(self, telegram_id: int):
        c = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (telegram_id,))
        if not c:
            return None
        i = self.db.one("SELECT * FROM contact_intelligence WHERE telegram_id=?", (telegram_id,))
        f = self.db.one("SELECT * FROM contact_forecasts WHERE telegram_id=?", (telegram_id,))
        opp = self.db.one(
            "SELECT COUNT(*) n FROM opportunities WHERE telegram_id=? AND status IN ('open','paused')",
            (telegram_id,),
        )["n"]
        if c["verification_status"] in {"unknown", "pending"} and int(c["relationship_score"] or 0) >= 60:
            name = "verification_review"
        elif f and int(f["disengagement_risk"] or 0) >= 60:
            name = "dormant_revival"
        elif opp:
            name = "opportunity_progress"
        elif c["relationship_type"] in {"supplier", "vendor"}:
            name = "supplier_management"
        elif c["relationship_type"] == "customer":
            name = "customer_nurture"
        elif c["relationship_type"] in {"vip", "partner"} or int(c["relationship_score"] or 0) >= 80:
            name = "vip_nurture"
        elif i and i["lifecycle_stage"] in {"cooling", "dormant", "returned"}:
            name = "dormant_revival"
        else:
            name = "relationship_development"
        return {"name": name, "steps": PLAYBOOKS[name]}

    def get(self, name: str):
        name = (name or "").strip().lower()
        if name not in PLAYBOOKS:
            return None
        return {"name": name, "steps": PLAYBOOKS[name]}
