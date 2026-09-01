from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .v4_schema import ensure_v4_schema


def _now():
    return datetime.now(timezone.utc).isoformat()


def _fp(service, category, details):
    return hashlib.sha256(json.dumps([service, category, details], sort_keys=True, default=str).encode()).hexdigest()[:24]


class PlatformNormalizer:
    """Read-only architecture hygiene scanner. It proposes normalization; it never moves/deletes source."""
    def __init__(self, store, root):
        self.store = store
        self.root = Path(root)
        ensure_v4_schema(store)

    def _violations_for(self, row):
        service = row.get("service") or "unknown"
        out = []
        if row.get("status") != "canonical":
            out.append(("runtime_unresolved", "high", "Canonical runtime is unresolved", row))
            return out
        if int(row.get("manifest_count") or 0) > 1:
            out.append(("multiple_manifests", "medium", "Multiple production-visible manifests exist", {"manifest_count": row.get("manifest_count")}))
        if int(row.get("candidate_count") or 0) > 1:
            out.append(("multiple_runnable_candidates", "medium", "Multiple runnable source candidates exist", {"candidate_count": row.get("candidate_count")}))
        if int(row.get("nested_depth") or 0) >= 2:
            out.append(("deep_nested_runtime", "medium", "Canonical runtime is deeply nested", {"nested_depth": row.get("nested_depth"), "canonical_root": row.get("canonical_root")}))
        if row.get("compatibility_entrypoint"):
            out.append(("compatibility_bridge_active", "low", "Legacy compatibility bridge is active", {"compatibility_entrypoint": row.get("compatibility_entrypoint")}))
        return out

    def refresh(self, registry_rows):
        now = _now()
        active = set()
        findings = []
        with self.store.connect() as con:
            for row in registry_rows:
                for category, severity, title, details in self._violations_for(row):
                    fp = _fp(row.get("service"), category, details)
                    active.add(fp)
                    evidence = json.dumps(details, sort_keys=True, default=str)
                    con.execute(
                        """
                        INSERT INTO architecture_violations(fingerprint,service,category,severity,title,details,status,first_seen_utc,last_seen_utc,evidence_json)
                        VALUES(?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(fingerprint) DO UPDATE SET status='open',last_seen_utc=excluded.last_seen_utc,
                          severity=excluded.severity,title=excluded.title,details=excluded.details,evidence_json=excluded.evidence_json
                        """,
                        (fp,row.get("service"),category,severity,title,title,"open",now,now,evidence),
                    )
                    findings.append({"fingerprint": fp, "service": row.get("service"), "category": category,
                                     "severity": severity, "title": title, "evidence": details})
            open_rows = con.execute("SELECT fingerprint FROM architecture_violations WHERE status='open'").fetchall()
            for old in open_rows:
                if old[0] not in active:
                    con.execute("UPDATE architecture_violations SET status='resolved',last_seen_utc=? WHERE fingerprint=?", (now, old[0]))
        score = max(0.0, 100.0 - sum({"high":25,"medium":10,"low":3}.get(x["severity"],5) for x in findings))
        plan = self.plan(findings)
        return {"score": round(score,1), "violations": findings, "normalization_plan": plan,
                "automatic_relocation": False, "note": "Source moves/deletes remain proposal-only."}

    def plan(self, findings):
        actions = []
        by_service = {}
        for f in findings:
            by_service.setdefault(f["service"], []).append(f)
        for service, rows in sorted(by_service.items()):
            cats = {x["category"] for x in rows}
            if "runtime_unresolved" in cats:
                actions.append({"service":service,"priority":100,"action":"resolve_canonical_runtime","automatic":False})
            if "multiple_runnable_candidates" in cats or "multiple_manifests" in cats:
                actions.append({"service":service,"priority":80,"action":"quarantine_legacy_runtime_candidates_after_diff_and_tests","automatic":False})
            if "deep_nested_runtime" in cats:
                actions.append({"service":service,"priority":65,"action":"normalize_folder_topology_via_guarded_migration","automatic":False})
            if "compatibility_bridge_active" in cats:
                actions.append({"service":service,"priority":40,"action":"retire_bridge_only_after_vm_core_registry_native_support","automatic":False})
        return sorted(actions,key=lambda x:(-x["priority"],x["service"]))
