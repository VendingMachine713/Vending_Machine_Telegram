from __future__ import annotations

import json
import sqlite3
import zipfile

from shared.vm_core.stabilization import (
    _backup_checks,
    _database_checks,
    _release_artifact_checks,
    write_stabilization_report,
)


def test_database_check_uses_read_only_integrity_check(tmp_path):
    database = tmp_path / "state" / "healthy.sqlite3"
    database.parent.mkdir()
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
    checks = _database_checks(tmp_path)
    assert len(checks) == 1
    assert checks[0].status == "PASS"
    assert checks[0].name == "state/healthy.sqlite3"


def test_backup_check_rejects_corrupt_latest_archive(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "vm_backup_manual_broken.zip").write_bytes(b"not a zip")
    with zipfile.ZipFile(backup_dir / "vm_intelligence_valid.zip", "w") as archive:
        archive.writestr("manifest.json", "{}")
    checks = _backup_checks(tmp_path)
    assert next(check for check in checks if check.name.startswith("vm_backup_")).status == "FAIL"


def test_backup_check_accepts_valid_archive(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for name in ("vm_backup_manual_valid.zip", "vm_intelligence_valid.zip"):
        with zipfile.ZipFile(backup_dir / name, "w") as archive:
            archive.writestr("manifest.json", "{}")
    checks = _backup_checks(tmp_path)
    assert len(checks) == 2
    assert all(check.status == "PASS" and check.detail["entries"] == 1 for check in checks)


def test_report_writes_json_and_text(tmp_path):
    report = {
        "generated_at_utc": "2026-09-01T00:00:00+00:00",
        "release_ready": False,
        "summary": {"PASS": 1, "WARN": 1, "FAIL": 1},
        "checks": [{"status": "FAIL", "category": "runtime", "name": "bot", "detail": "stale"}],
    }
    json_path, text_path = write_stabilization_report(report, tmp_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["release_ready"] is False
    assert "FAIL  runtime" in text_path.read_text(encoding="utf-8")


def test_missing_v6_release_artifacts_fail_closed(tmp_path):
    checks = _release_artifact_checks(tmp_path)
    assert len(checks) == 3
    assert all(check.status == "FAIL" for check in checks)
