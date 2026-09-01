from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import hashlib

class TestingIntelligence:
    def __init__(self,store,root):self.store=store;self.root=Path(root)

    def impact_plan(self, release_changes, incidents):
        suites=[];proposals=[]
        for c in release_changes:
            bot=c["source"];root=self.root/"bots"/bot
            tests=sorted(root.glob("**/tests/test_*.py"),key=lambda p:len(p.parts))
            suites.append({"source":bot,"tests":[str(p.relative_to(self.root)) for p in tests]})
        for inc in incidents:
            if inc["severity"] not in {"critical","high"}:continue
            title=f"Regression coverage for {inc['category'].replace('_',' ')}"
            suggested=(
                f"Create a deterministic regression test for {inc['source']} that reproduces "
                f"the {inc['category']} condition, asserts the safe failure mode, and verifies "
                "recovery/duplicate-suppression behavior where applicable."
            )
            fp=hashlib.sha256(f"{inc['source']}:{inc['category']}".encode()).hexdigest()[:24]
            now=datetime.now(timezone.utc).isoformat()
            with self.store.connect() as con:
                con.execute("""INSERT INTO test_proposals(
                    fingerprint,source,incident_id,title,rationale,suggested_test,created_at_utc,updated_at_utc)
                    VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(fingerprint) DO UPDATE SET updated_at_utc=excluded.updated_at_utc,
                      incident_id=excluded.incident_id,rationale=excluded.rationale,suggested_test=excluded.suggested_test
                """,(fp,inc["source"],inc["incident_id"],title,
                     "A high-severity operational incident should become permanent regression coverage.",
                     suggested,now,now))
            proposals.append({"source":inc["source"],"title":title,"suggested_test":suggested})
        return {"impact_suites":suites,"regression_test_proposals":proposals}
