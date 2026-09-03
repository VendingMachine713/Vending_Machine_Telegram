from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json
from typing import Any

from . import __version__
from .config import load_config, validate_config
from .manifests import discover_bots
from .paths import project_root

CONTRACT_VERSION = 1
REQUIRED_MANIFEST_FIELDS = (
    "schema_version",
    "name",
    "version",
    "classification",
    "entrypoint",
    "launchers",
    "vm_core",
    "lifecycle",
)

@dataclass(frozen=True)
class ContractFinding:
    severity: str
    scope: str
    code: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

def _load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None, "file is missing"
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(data, dict):
        return None, "top-level JSON value must be an object"
    return data, None

def validate_bot_contract(bot_dir: Path) -> list[ContractFinding]:
    findings: list[ContractFinding] = []
    scope = bot_dir.name
    manifest_path = bot_dir / "BOT_MANIFEST.json"
    manifest, error = _load_json(manifest_path)
    if error:
        return [ContractFinding("ERROR", scope, "MANIFEST_UNREADABLE", error)]
    assert manifest is not None

    for field in REQUIRED_MANIFEST_FIELDS:
        if field not in manifest:
            findings.append(ContractFinding("ERROR", scope, "MANIFEST_FIELD_MISSING", field))

    if manifest.get("name") != scope:
        findings.append(ContractFinding(
            "ERROR", scope, "MANIFEST_NAME_MISMATCH",
            f"manifest name={manifest.get('name')!r}; folder={scope!r}",
        ))

    schema = manifest.get("schema_version")
    if not isinstance(schema, int) or schema < 3:
        findings.append(ContractFinding(
            "ERROR", scope, "MANIFEST_SCHEMA_UNSUPPORTED",
            f"schema_version={schema!r}; minimum=3",
        ))

    vm_core = manifest.get("vm_core")
    if not isinstance(vm_core, dict) or vm_core.get("compatible") is not True:
        findings.append(ContractFinding(
            "ERROR", scope, "VM_CORE_COMPATIBILITY",
            "vm_core.compatible must be true",
        ))

    lifecycle = manifest.get("lifecycle")
    if not isinstance(lifecycle, dict):
        findings.append(ContractFinding("ERROR", scope, "LIFECYCLE_INVALID", "lifecycle must be an object"))
    else:
        for key in ("managed_by_vm", "auto_start", "auto_restart"):
            if key not in lifecycle or not isinstance(lifecycle[key], bool):
                findings.append(ContractFinding(
                    "ERROR", scope, "LIFECYCLE_FIELD_INVALID",
                    f"lifecycle.{key} must be boolean",
                ))

    classification = manifest.get("classification")
    entrypoint = manifest.get("entrypoint")
    if classification == "CANONICAL":
        if entrypoint:
            target = bot_dir / str(entrypoint)
            if not target.is_file():
                findings.append(ContractFinding(
                    "ERROR", scope, "ENTRYPOINT_MISSING",
                    f"{entrypoint} does not exist",
                ))
        elif not manifest.get("launchers"):
            findings.append(ContractFinding(
                "ERROR", scope, "RUNNABLE_TARGET_MISSING",
                "canonical bot requires an entrypoint or launcher",
            ))

    launchers = manifest.get("launchers", [])
    if not isinstance(launchers, list):
        findings.append(ContractFinding("ERROR", scope, "LAUNCHERS_INVALID", "launchers must be a list"))
    else:
        for launcher in launchers:
            if not isinstance(launcher, str):
                findings.append(ContractFinding("ERROR", scope, "LAUNCHER_INVALID", "launcher names must be strings"))
            elif not (bot_dir / launcher).is_file():
                findings.append(ContractFinding(
                    "WARN", scope, "LAUNCHER_MISSING",
                    f"{launcher} does not exist",
                ))

    capabilities = manifest.get("capabilities", [])
    if capabilities is not None and (
        not isinstance(capabilities, list)
        or any(not isinstance(item, str) or not item.strip() for item in capabilities)
    ):
        findings.append(ContractFinding(
            "ERROR", scope, "CAPABILITIES_INVALID",
            "capabilities must be a list of non-empty strings",
        ))

    runtime = manifest.get("runtime_requirements", {})
    if runtime is not None and not isinstance(runtime, dict):
        findings.append(ContractFinding(
            "ERROR", scope, "RUNTIME_REQUIREMENTS_INVALID",
            "runtime_requirements must be an object",
        ))

    return findings

def foundation_report(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    findings: list[ContractFinding] = []

    project_path = root / "VM_PROJECT.json"
    project, project_error = _load_json(project_path)
    if project_error:
        findings.append(ContractFinding("ERROR", "platform", "PROJECT_FILE_INVALID", project_error))
        project = {}

    bots = discover_bots(root)
    actual = {bot.folder for bot in bots}
    declared = set(project.get("canonical_bot_folders", [])) if isinstance(project, dict) else set()

    for name in sorted(declared - actual):
        findings.append(ContractFinding("ERROR", "platform", "DECLARED_BOT_MISSING", name))
    for name in sorted(actual - declared):
        findings.append(ContractFinding("WARN", "platform", "UNDECLARED_BOT", name))

    for bot in bots:
        findings.extend(validate_bot_contract(Path(bot.path)))

    config = load_config(root)
    for issue in validate_config(config):
        findings.append(ContractFinding(issue["severity"], "config", issue["code"], issue["detail"]))

    counts = {
        severity: sum(1 for f in findings if f.severity == severity)
        for severity in ("INFO", "WARN", "ERROR")
    }
    return {
        "contract_version": CONTRACT_VERSION,
        "vm_core_version": __version__,
        "project": project.get("project", root.name) if isinstance(project, dict) else root.name,
        "bot_count": len(bots),
        "declared_bot_count": len(declared),
        "status": "FAIL" if counts["ERROR"] else ("WARN" if counts["WARN"] else "PASS"),
        "summary": counts,
        "findings": [finding.to_dict() for finding in findings],
    }

def format_foundation_report(report: dict[str, Any]) -> str:
    lines = [
        "=" * 78,
        f" VM CORE FOUNDATION CONTRACT v{report['contract_version']}",
        "=" * 78,
        f"VM Core: {report['vm_core_version']}",
        f"Bots:    {report['bot_count']} discovered / {report['declared_bot_count']} declared",
        f"Status:  {report['status']}",
        "",
    ]
    if not report["findings"]:
        lines.append("[PASS] All discovered bots satisfy the VM Core foundation contract.")
    else:
        for finding in report["findings"]:
            lines.append(
                f"[{finding['severity']:<5}] {finding['scope']}/{finding['code']}: {finding['detail']}"
            )
    lines += [
        "",
        f"Summary: ERROR={report['summary']['ERROR']} WARN={report['summary']['WARN']} INFO={report['summary']['INFO']}",
    ]
    return "\n".join(lines)
