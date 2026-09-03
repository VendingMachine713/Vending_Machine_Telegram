from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from database import Database, utcnow


class BackupManager:
    """Consistent SQLite backups with checksum verification and retention."""
    def __init__(self, db: Database, backup_dir: Path, retention: int = 21):
        self.db = db
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.retention = max(7, int(retention))

    @staticmethod
    def sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024*1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def create(self, kind: str = "scheduled"):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        target = self.backup_dir / f"vm_relationships_{stamp}.db"
        src = sqlite3.connect(self.db.path)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        finally:
            dst.close(); src.close()
        checksum = self.sha256(target)
        size = target.stat().st_size
        con = sqlite3.connect(target)
        try:
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            con.close()
        status = "verified" if integrity == "ok" else "invalid"
        manifest = target.with_suffix(".json")
        manifest.write_text(json.dumps({
            "file": target.name, "created_at": utcnow(), "kind": kind,
            "sha256": checksum, "bytes": size, "integrity": integrity,
            "schema_version": self.db.meta("schema_version", "unknown"),
        }, indent=2, sort_keys=True), encoding="utf-8")
        self.db.execute(
            "INSERT INTO backup_audit(path,kind,sha256,size_bytes,integrity_status,created_at) VALUES (?,?,?,?,?,?)",
            (str(target), kind, checksum, size, status, utcnow()),
        )
        self.prune()
        return {"path": str(target), "manifest": str(manifest), "sha256": checksum, "bytes": size, "status": status}


    def verify_record(self, record=None):
        """Re-verify an audited backup against disk, checksum, size and SQLite integrity."""
        record = record or self.db.one("SELECT * FROM backup_audit ORDER BY id DESC LIMIT 1")
        if not record:
            return {"status": "missing", "reason": "no backup audit entry"}
        try:
            path = Path(record["path"])
            if not path.exists():
                return {"status": "missing", "reason": "backup file is missing", "path": str(path)}
            actual_size = path.stat().st_size
            expected_size = int(record["size_bytes"] or 0)
            if expected_size and actual_size != expected_size:
                return {"status": "invalid", "reason": "backup size does not match audit", "path": str(path)}
            actual_sha = self.sha256(path)
            expected_sha = str(record["sha256"] or "").lower()
            if expected_sha and actual_sha.lower() != expected_sha:
                return {"status": "invalid", "reason": "backup checksum does not match audit", "path": str(path)}
            con = sqlite3.connect(path)
            try:
                integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                con.close()
            if integrity != "ok":
                return {"status": "invalid", "reason": f"SQLite integrity_check: {integrity}", "path": str(path)}
            return {
                "status": "verified",
                "reason": "checksum, size and SQLite integrity verified",
                "path": str(path),
                "sha256": actual_sha,
                "bytes": actual_size,
            }
        except Exception as exc:
            return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}

    def prune(self):
        backups = sorted(self.backup_dir.glob("vm_relationships_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[self.retention:]:
            old.unlink(missing_ok=True)
            old.with_suffix(".json").unlink(missing_ok=True)

    def recent(self, limit: int = 10):
        return self.db.all("SELECT * FROM backup_audit ORDER BY id DESC LIMIT ?", (limit,))
