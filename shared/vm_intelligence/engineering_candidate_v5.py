from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import hashlib, json
from .v5_schema import ensure_v5_schema

def _now():return datetime.now(timezone.utc).isoformat()

class EngineeringCandidateManager:
    """Creates evidence records for isolated engineering only. Never edits production source."""
    def __init__(self,store,root):self.store=store;self.root=Path(root);ensure_v5_schema(store)

    def propose(self,title,issue_source=None,regression_test=None,patch_summary=None):
        key=hashlib.sha256(f"{issue_source}|{title}".encode()).hexdigest()[:20]
        workspace=str(self.root/"state"/"engineering_worktrees"/key)
        now=_now()
        with self.store.connect() as con:
            con.execute("""INSERT INTO engineering_candidates(candidate_key,issue_source,title,workspace,
              regression_test,patch_summary,targeted_status,full_status,security_status,production_mutation,
              release_gate_status,created_at_utc,updated_at_utc,metadata_json)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(candidate_key) DO UPDATE SET regression_test=excluded.regression_test,
              patch_summary=excluded.patch_summary,updated_at_utc=excluded.updated_at_utc""",
              (key,issue_source,title,workspace,regression_test,patch_summary,"pending","pending","pending",0,None,now,now,
               json.dumps({"required_sequence":["create isolated worktree","prove regression test fails","apply candidate patch",
               "targeted tests","full regression","security scan","release gate"]})))
        return {"candidate_key":key,"title":title,"workspace":workspace,"production_mutation":False,
                "execution_mode":"isolated_only","release_required":True}

    def list(self):
        with self.store.connect() as con:
            return [dict(r) for r in con.execute("SELECT * FROM engineering_candidates ORDER BY candidate_id DESC").fetchall()]
