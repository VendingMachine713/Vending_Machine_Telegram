from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import hashlib, json

from .v42_schema import ensure_v42_schema
from .runtime_registry import RuntimeRegistry

EXCLUDED={"archive","backups","venv",".venv","__pycache__",".git","runtime","sessions","logs"}

def _now(): return datetime.now(timezone.utc).isoformat()

def _hash(path:Path):
    try:
        h=hashlib.sha256()
        with path.open("rb") as f:
            for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
        return h.hexdigest()
    except Exception:return None

def _bounded_files(root:Path,suffixes:set[str],limit=40):
    rows=[]
    if not root.is_dir():return rows
    try:
        for p in root.rglob("*"):
            if len(rows)>=limit:break
            if not p.is_file() or any(part.lower() in EXCLUDED for part in p.parts):continue
            if p.suffix.lower() in suffixes or p.name.lower() in {".env",".env.local",".env.production"}:
                rows.append(p.resolve())
    except Exception:pass
    return sorted(set(rows),key=lambda p:str(p).casefold())

class PlatformServiceRegistry:
    """Authoritative service inventory derived from the tested runtime registry.

    It records ownership/config/database/dependency metadata but does not move or rewrite bot source.
    """
    def __init__(self,store,root):
        self.store=store;self.root=Path(root);ensure_v42_schema(store)
        self.runtime=RuntimeRegistry(store,self.root)

    def _dependencies(self,service):
        try:
            with self.store.connect() as con:
                rows=con.execute(
                    "SELECT source,target,edge_type,confidence FROM dependency_edges WHERE target=? OR source=? ORDER BY source,target",
                    (service,service)).fetchall()
            return [dict(r) for r in rows]
        except Exception:return []

    def _inventory_paths(self,row):
        bot=self.root/"bots"/row["service"]
        configs=_bounded_files(bot,{".json",".toml",".ini",".cfg",".yaml",".yml"},30)
        dbs=_bounded_files(bot,{".db",".sqlite",".sqlite3"},20)
        # Shared config files that name the service are useful ownership evidence.
        shared_cfg=self.root/"shared"/"config"
        if shared_cfg.is_dir():
            for p in _bounded_files(shared_cfg,{".json",".toml",".ini",".cfg",".yaml",".yml"},30):
                if row["service"].lower().replace("_","") in p.name.lower().replace("_",""):
                    configs.append(p)
        configs=sorted(set(configs),key=lambda p:str(p).casefold())
        return configs,dbs

    def refresh(self,runtime_rows=None):
        runtime_rows=runtime_rows or self.runtime.refresh()
        now=_now();out=[]
        with self.store.connect() as con:
            previous={x["service"]:dict(x) for x in con.execute("SELECT service,runtime_id,canonical_entrypoint,source_hash,topology_hash FROM platform_services").fetchall()}
            for r in runtime_rows:
                if r.get("status")!="canonical":continue
                configs,dbs=self._inventory_paths(r)
                deps=self._dependencies(r["service"])
                health="RuntimeBridge" if r.get("compatibility_entrypoint") and r.get("managed") else ("VM_Core" if r.get("managed") else r["service"])
                row={
                    **r,
                    "classification":"CANONICAL",
                    "owner":r["service"],
                    "health_provider":health,
                    "telemetry_provider":"VM_Intelligence",
                    "database_paths":[str(x) for x in dbs],
                    "config_paths":[str(x) for x in configs],
                    "dependencies":deps,
                    "last_verified_utc":now,
                    "previous_runtime_id":(previous.get(r["service"]) or {}).get("runtime_id"),
                    "previous_canonical_entrypoint":(previous.get(r["service"]) or {}).get("canonical_entrypoint"),
                    "previous_source_hash":(previous.get(r["service"]) or {}).get("source_hash"),
                    "previous_topology_hash":(previous.get(r["service"]) or {}).get("topology_hash"),
                }
                row["runtime_identity_changed"]=bool(row["previous_runtime_id"] and row["previous_runtime_id"]!=row["runtime_id"])
                row["source_changed"]=bool(row["previous_source_hash"] and row.get("source_hash") and row["previous_source_hash"]!=row.get("source_hash"))
                row["topology_changed"]=bool(row["previous_topology_hash"] and row.get("topology_hash") and row["previous_topology_hash"]!=row.get("topology_hash"))
                row["is_baseline_observation"]=not bool(row["previous_runtime_id"])
                out.append(row)
                con.execute("""
                    INSERT INTO platform_services(service,runtime_id,canonical_root,canonical_entrypoint,
                      compatibility_entrypoint,manifest_path,version,classification,managed,auto_start,auto_restart,
                      owner,health_provider,telemetry_provider,database_paths_json,config_paths_json,dependencies_json,
                      source_hash,topology_hash,last_verified_utc,status,metadata_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(service) DO UPDATE SET
                      runtime_id=excluded.runtime_id,canonical_root=excluded.canonical_root,
                      canonical_entrypoint=excluded.canonical_entrypoint,
                      compatibility_entrypoint=excluded.compatibility_entrypoint,manifest_path=excluded.manifest_path,
                      version=excluded.version,classification=excluded.classification,managed=excluded.managed,
                      auto_start=excluded.auto_start,auto_restart=excluded.auto_restart,owner=excluded.owner,
                      health_provider=excluded.health_provider,telemetry_provider=excluded.telemetry_provider,
                      database_paths_json=excluded.database_paths_json,config_paths_json=excluded.config_paths_json,
                      dependencies_json=excluded.dependencies_json,source_hash=excluded.source_hash,
                      topology_hash=excluded.topology_hash,last_verified_utc=excluded.last_verified_utc,
                      status=excluded.status,metadata_json=excluded.metadata_json
                """,(
                    row["service"],row["runtime_id"],row["canonical_root"],row["canonical_entrypoint"],
                    row.get("compatibility_entrypoint"),row.get("manifest_path"),row.get("version"),
                    row["classification"],1 if row.get("managed") else 0,1 if row.get("auto_start") else 0,
                    1 if row.get("auto_restart") else 0,row["owner"],row["health_provider"],row["telemetry_provider"],
                    json.dumps(row["database_paths"]),json.dumps(row["config_paths"]),
                    json.dumps(row["dependencies"],sort_keys=True,default=str),row.get("source_hash"),
                    row.get("topology_hash"),now,row.get("status","canonical"),
                    json.dumps({"discovery_confidence":row.get("discovery_confidence"),
                                "manifest_count":row.get("manifest_count"),"candidate_count":row.get("candidate_count"),
                                "nested_depth":row.get("nested_depth")},sort_keys=True)
                ))
        self._write_state(out)
        return out

    def _write_state(self,rows):
        p=self.root/"state"/"platform_service_registry.json";p.parent.mkdir(parents=True,exist_ok=True)
        payload={"schema_version":2,"generated_at_utc":_now(),"authoritative_for":
                 ["runtime identity","canonical source","service ownership","config/database inventory","dependency metadata"],
                 "services":rows}
        p.write_text(json.dumps(payload,indent=2,default=str),encoding="utf-8")

    def current(self):
        with self.store.connect() as con:
            rows=[dict(r) for r in con.execute("SELECT * FROM platform_services ORDER BY service").fetchall()]
        for r in rows:
            for src,dst in [("database_paths_json","database_paths"),("config_paths_json","config_paths"),
                            ("dependencies_json","dependencies"),("metadata_json","metadata")]:
                try:r[dst]=json.loads(r.pop(src))
                except Exception:r[dst]=[] if dst!="metadata" else {}
        return rows
