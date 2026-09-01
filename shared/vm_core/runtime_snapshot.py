from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Any
from .paths import project_root
from .services import service_status, managed_services
from .health import run_health
from .autostart import status as autostart_status
from .search_index import SearchIndex
from .db import PlatformDB
from .relationship_cleanup import plan as relationship_cleanup_plan
from .legacy_recovery import recover as legacy_recovery_status
from .components import read_components


def _age_seconds(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())
    except Exception:
        return None


def collect(root: Path | None = None) -> dict[str,Any]:
    root = root or project_root()
    services = service_status(root)
    health = run_health(root)
    db = PlatformDB(root=root); db.init()
    managed = managed_services(root)
    components = read_components(root)
    for data in components.values():
        data["age_seconds"] = _age_seconds(data.get("updated_at_utc"))
    try:
        search = SearchIndex(root).stats()
    except Exception as exc:
        search = {"error":f"{type(exc).__name__}: {exc}"}
    return {
        "schema_version":2,
        "generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "services":services,
        "health":health,
        "managed_services":managed,
        "managed_alive":{
            row["name"]:bool(row.get("process_alive"))
            for row in services if row["name"] in managed
        },
        "autostart":autostart_status(root),
        "search":search,
        "open_alerts":db.alerts(100),
        "components":components,
        "legacy_recovery":legacy_recovery_status(root,apply=False),
        "relationship_cleanup":relationship_cleanup_plan(root),
    }


def verify(root: Path | None = None, *, require_autostart: bool = False,
           require_legacy_components: bool = False) -> dict[str,Any]:
    root = root or project_root()
    data = collect(root)
    failures=[]; warnings=[]
    for name, alive in data["managed_alive"].items():
        if not alive:
            failures.append(f"managed service not alive: {name}")
    if require_autostart and data["autostart"].get("supported") and not data["autostart"].get("registered"):
        failures.append("Windows autostart is not registered")
    required_component_services = {
        name for name in data["managed_services"]
        if name in {"Universal_Search", "VM_Guard"}
    }
    for name in required_component_services:
        if name not in data["components"]:
            failures.append(f"managed component heartbeat missing: {name}")

    for service, comp in data["components"].items():
        age=comp.get("age_seconds")
        if age is not None and age > 180:
            warnings.append(f"component heartbeat stale: {service} ({age:.0f}s)")
        expected=bool(comp.get("legacy_component_expected"))
        legacy=comp.get("legacy_component") or {}
        if expected and not legacy.get("alive"):
            msg=f"legacy Telegram component not alive: {service}"
            if require_legacy_components:
                failures.append(msg)
            else:
                warnings.append(msg)

    if require_legacy_components:
        for service in ("Universal_Search", "VM_Guard"):
            bot_dir=root/"bots"/service
            if not bot_dir.is_dir():
                continue
            evidence=any((bot_dir/name).exists() for name in ("core.py","envutil.py",".env"))
            if evidence and not (bot_dir/"legacy_main.py").is_file():
                failures.append(f"legacy component evidence present but entrypoint missing: {service}")

    return {"ok":not failures,"failures":failures,"warnings":warnings,"snapshot":data}


def write_report(root: Path | None = None) -> tuple[Path,Path]:
    root = root or project_root()
    data = collect(root)
    out = root/"diagnostics"; out.mkdir(parents=True,exist_ok=True)
    jp = out/"live_runtime.json"; tp = out/"live_runtime.txt"
    jp.write_text(json.dumps(data,indent=2,ensure_ascii=False,default=str)+"\n",encoding="utf-8")
    lines=["="*72,"VM LIVE RUNTIME SNAPSHOT","="*72,
           f"Generated: {data['generated_at_utc']}","",
           "SERVICES","-"*72]
    by_health={x["service"]:x["status"] for x in data["health"]}
    for row in data["services"]:
        lines.append(
            f"{('RUNNING' if row.get('process_alive') else 'STOPPED'):<9} "
            f"{by_health.get(row['name'],'UNKNOWN'):<15} {row['name']} "
            f"pid={row.get('pid') or '-'}"
        )
    lines += ["","MANAGED SERVICES","-"*72]
    for name,alive in data["managed_alive"].items():
        lines.append(f"{'ALIVE' if alive else 'NOT RUNNING':<12} {name}")
    lines += ["","COMPONENTS","-"*72]
    if not data["components"]:
        lines.append("No component heartbeats yet.")
    for name,comp in data["components"].items():
        legacy=comp.get("legacy_component") or {}
        lines.append(f"{name}: heartbeat_age={comp.get('age_seconds')} legacy_expected={comp.get('legacy_component_expected')} legacy_alive={legacy.get('alive')}")
    lines += ["","AUTOSTART","-"*72,
              f"registered={data['autostart'].get('registered','n/a')}",
              f"method={data['autostart'].get('method','n/a')}",
              "","SEARCH","-"*72,json.dumps(data["search"],ensure_ascii=False),
              "","ALERTS","-"*72,f"open={len(data['open_alerts'])}",
              "","RELATIONSHIP CLEANUP","-"*72,
              f"safe_to_apply={data['relationship_cleanup'].get('safe_to_apply',False)}",
              f"outer_version={data['relationship_cleanup'].get('outer_version')}",
              f"nested_version={data['relationship_cleanup'].get('nested_version')}"]
    tp.write_text("\n".join(lines)+"\n",encoding="utf-8")
    return jp,tp
