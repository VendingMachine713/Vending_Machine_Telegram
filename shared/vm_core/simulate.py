from __future__ import annotations
from pathlib import Path
from .paths import project_root
from .events import emit
from .jobs import enqueue

SCENARIOS = {
    "spam": [
        ("message.received", {"sender":"fake_spammer","text":"repeated advertisement","risk":0.99}),
        ("guard.spam_detected", {"sender":"fake_spammer","confidence":0.99,"dry_run":True}),
    ],
    "outage": [
        ("telegram.connection_lost", {"account":"PRIMARY","simulated":True}),
        ("service.degraded", {"service":"simulated","reason":"telegram outage"}),
    ],
    "campaign": [
        ("campaign.due", {"campaign":"simulation","destinations":56,"dry_run":True}),
        ("campaign.preview", {"would_send":56,"sent":0}),
    ],
    "deleted-account": [
        ("member.deleted_account_detected", {"user_id":"fake_deleted","dry_run":True}),
        ("cleanup.review_required", {"count":1}),
    ],
}

def run_scenario(name: str, root: Path | None = None):
    root=root or project_root()
    if name not in SCENARIOS:
        raise KeyError(f"Unknown scenario {name}; choose: {', '.join(SCENARIOS)}")
    ids=[]
    for event_type,payload in SCENARIOS[name]:
        ids.append(emit(event_type,"simulator",payload,root))
    jid=enqueue("SIM_"+name.upper().replace("-","_"),{"scenario":name},root)
    return {"scenario":name,"event_ids":ids,"job_id":jid,"real_telegram_actions":0}
