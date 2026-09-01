from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import subprocess
import zipfile
from typing import Any

from .health import run_health


@dataclass(frozen=True)
class Check:
    category: str
    name: str
    status: str
    detail: Any


def _run(root: Path, *args: str) -> tuple[int, str]:
    completed = subprocess.run(
        list(args), cwd=root, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=False, timeout=30
    )
    return completed.returncode, (completed.stdout or completed.stderr).strip()


def _database_checks(root: Path) -> list[Check]:
    checks: list[Check] = []
    excluded = {"backups", "archive", ".git", ".venv", "venv"}
    databases: set[Path] = set()
    for pattern in ("*.db", "*.sqlite", "*.sqlite3"):
        for path in root.rglob(pattern):
            if path.is_file() and not any(part.lower() in excluded for part in path.parts):
                databases.add(path)
    for path in sorted(databases):
        relative = path.relative_to(root).as_posix()
        try:
            connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=3)
            try:
                result = connection.execute("PRAGMA quick_check").fetchone()
            finally:
                connection.close()
            value = str(result[0]) if result else "no result"
            checks.append(Check("database", relative, "PASS" if value.lower() == "ok" else "FAIL", value))
        except sqlite3.Error as exc:
            checks.append(Check("database", relative, "FAIL", type(exc).__name__))
    if not checks:
        checks.append(Check("database", "discovery", "FAIL", "no live databases discovered"))
    return checks


def _backup_checks(root: Path) -> list[Check]:
    archives = sorted((root / "backups").glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    checks: list[Check] = []
    selected: list[Path] = []
    for prefix in ("vm_backup_", "vm_intelligence_"):
        latest = next((path for path in archives if path.name.lower().startswith(prefix)), None)
        if latest:
            selected.append(latest)
        else:
            checks.append(Check("backup", prefix.rstrip("_"), "FAIL", "backup family missing"))
    for path in selected:
        try:
            with zipfile.ZipFile(path) as archive:
                corrupt = archive.testzip()
                names = set(archive.namelist())
            status = "PASS" if corrupt is None else "FAIL"
            checks.append(Check("backup", path.name, status, {"bytes": path.stat().st_size, "corrupt": corrupt, "entries": len(names)}))
        except (OSError, zipfile.BadZipFile) as exc:
            checks.append(Check("backup", path.name, "FAIL", type(exc).__name__))
    if not checks:
        checks.append(Check("backup", "latest", "FAIL", "no backup archives found"))
    return checks


def _version_config_checks(root: Path) -> list[Check]:
    registry_path = root / "state" / "runtime_registry.json"
    config_path = root / "state" / "config_registry.json"
    checks: list[Check] = []
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return [Check("drift", "runtime_registry", "FAIL", type(exc).__name__)]
    for service in registry.get("services", []):
        name = str(service.get("service", "unknown"))
        registry_version = str(service.get("version", "unknown"))
        manifest_path = Path(str(service.get("manifest_path", "")))
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            manifest_version = str(manifest.get("version", "unknown"))
        except (OSError, json.JSONDecodeError):
            manifest_version = "unreadable"
        version_file = root / "bots" / name / "VERSION.txt"
        version_text = version_file.read_text(encoding="utf-8-sig").strip() if version_file.is_file() else None
        versions_match = manifest_version == registry_version and (
            version_text is None or registry_version in version_text
        )
        topology_clean = int(service.get("manifest_count", 0)) <= 1 and int(service.get("nested_depth", 0)) == 0
        checks.append(Check("drift", f"{name}.version", "PASS" if versions_match else "WARN", {
            "registry": registry_version, "manifest": manifest_version, "version_file": version_text
        }))
        checks.append(Check("drift", f"{name}.topology", "PASS" if topology_clean else "WARN", {
            "manifest_count": service.get("manifest_count"), "nested_depth": service.get("nested_depth"),
            "canonical_root": service.get("canonical_root")
        }))
    try:
        configs = json.loads(config_path.read_text(encoding="utf-8-sig")).get("configs", [])
        by_service: dict[str, set[str]] = {}
        for row in configs:
            if row.get("role") == "environment" and row.get("exists"):
                by_service.setdefault(str(row.get("service")), set()).add(str(row.get("sha256")))
        for service, hashes in sorted(by_service.items()):
            checks.append(Check("drift", f"{service}.environment", "PASS" if len(hashes) == 1 else "WARN", {
                "distinct_secret_configurations": len(hashes)
            }))
    except (OSError, json.JSONDecodeError) as exc:
        checks.append(Check("drift", "config_registry", "FAIL", type(exc).__name__))
    return checks


def _git_checks(root: Path, reference: str) -> list[Check]:
    checks: list[Check] = []
    code, branch = _run(root, "git", "branch", "--show-current")
    checks.append(Check("git", "branch", "PASS" if code == 0 else "FAIL", branch))
    code, status = _run(root, "git", "status", "--porcelain")
    lines = status.splitlines() if code == 0 else []
    checks.append(Check("git", "working_tree", "WARN" if lines else ("PASS" if code == 0 else "FAIL"), {"changes": len(lines)}))
    code, _ = _run(root, "git", "rev-parse", "--verify", reference)
    if code != 0:
        checks.append(Check("git", "v6_reference", "FAIL", f"missing {reference}"))
        return checks
    local = root / "shared" / "vm_intelligence"
    tracked_code, tracked = _run(root, "git", "ls-tree", "-r", "--name-only", reference, "--", "shared/vm_intelligence")
    remote_paths = set(tracked.splitlines()) if tracked_code == 0 else set()
    local_paths = {p.relative_to(root).as_posix() for p in local.rglob("*.py")} if local.is_dir() else set()
    different = 0
    identical = 0
    changed_paths: list[str] = []
    for path in sorted(remote_paths & local_paths):
        local_text = (root / path).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        show_code, remote_text = _run(root, "git", "show", f"{reference}:{path}")
        remote_text = remote_text.lstrip("\ufeff").replace("\r\n", "\n")
        if show_code == 0 and local_text.rstrip("\n") == remote_text.rstrip("\n"):
            identical += 1
        else:
            different += 1
            changed_paths.append(path)
    detail = {
        "reference": reference,
        "identical": identical,
        "different": different,
        "missing_local": len(remote_paths - local_paths),
        "local_only": len(local_paths - remote_paths),
        "changed_paths": changed_paths[:50],
    }
    status_value = "PASS" if different == 0 and not (remote_paths - local_paths) and not (local_paths - remote_paths) else "WARN"
    checks.append(Check("git", "v6_reconciliation", status_value, detail))
    return checks


def _script_checks(root: Path) -> list[Check]:
    candidates = sorted(root.glob("INSTALL*.ps1")) + sorted(root.glob("ROLLBACK*.ps1"))
    candidates += sorted((root / "bots").glob("*/INSTALL*.ps1"))
    candidates += sorted((root / "bots").glob("*/RECOVER*.ps1"))
    checks: list[Check] = []
    for path in candidates:
        escaped_path = str(path).replace("'", "''")
        command = (
            "$e=$null;$t=$null;[System.Management.Automation.Language.Parser]::ParseFile"
            f"('{escaped_path}',[ref]$t,[ref]$e)|Out-Null;"
            "if($e.Count){$e|ForEach-Object{$_.Message};exit 2}"
        )
        code, output = _run(root, "powershell.exe", "-NoProfile", "-Command", command)
        checks.append(Check("procedure", path.relative_to(root).as_posix(), "PASS" if code == 0 else "FAIL", output or "syntax valid"))
    if not checks:
        checks.append(Check("procedure", "discovery", "FAIL", "no install/recovery scripts found"))
    return checks


def _release_artifact_checks(root: Path) -> list[Check]:
    checks: list[Check] = []
    required = (
        "INSTALL_VM_INTELLIGENCE_v6.0.0.ps1",
        "INSTALL_VM_INTELLIGENCE_v6.0.0_FROM_CMD.bat",
        "VM_INTELLIGENCE_RELEASE.json",
    )
    for relative in required:
        path = root / relative
        checks.append(Check("release", relative, "PASS" if path.is_file() and path.stat().st_size else "FAIL", {
            "exists": path.is_file(), "bytes": path.stat().st_size if path.is_file() else 0
        }))
    manifest = root / "VM_INTELLIGENCE_RELEASE.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8-sig"))
            version = str(data.get("version", "unknown"))
            checks.append(Check("release", "v6_manifest_version", "PASS" if version == "6.0.0" else "FAIL", version))
        except json.JSONDecodeError as exc:
            checks.append(Check("release", "v6_manifest_json", "FAIL", type(exc).__name__))
    return checks


def run_stabilization(root: Path, reference: str = "origin/dev/v6.2-brain-native-fabric-final2") -> dict[str, Any]:
    root = root.resolve()
    checks: list[Check] = []
    for row in run_health(root):
        runtime = row.get("detail", {}).get("runtime_status")
        process_alive = bool(row.get("detail", {}).get("process_alive"))
        status = "PASS" if process_alive else ("WARN" if row.get("status") in {"READY", "PLANNED"} else "FAIL")
        checks.append(Check("runtime", row["service"], status, {"health": row.get("status"), "runtime": runtime, "process_alive": process_alive}))
    checks.extend(_database_checks(root))
    checks.extend(_backup_checks(root))
    checks.extend(_version_config_checks(root))
    checks.extend(_git_checks(root, reference))
    checks.extend(_script_checks(root))
    checks.extend(_release_artifact_checks(root))
    counts = {name: sum(c.status == name for c in checks) for name in ("PASS", "WARN", "FAIL")}
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "release_ready": counts["FAIL"] == 0 and counts["WARN"] == 0,
        "summary": counts,
        "checks": [asdict(c) for c in checks],
    }


def write_stabilization_report(report: dict[str, Any], root: Path) -> tuple[Path, Path]:
    output = root / "diagnostics"
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "stabilization_report.json"
    text_path = output / "stabilization_report.txt"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "VM PLATFORM STABILIZATION REPORT",
        "=" * 78,
        f"Generated: {report['generated_at_utc']}",
        f"Release ready: {report['release_ready']}",
        f"PASS={report['summary']['PASS']} WARN={report['summary']['WARN']} FAIL={report['summary']['FAIL']}",
        "",
    ]
    lines.extend(f"{c['status']:<5} {c['category']:<12} {c['name']}: {c['detail']}" for c in report["checks"])
    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, text_path
