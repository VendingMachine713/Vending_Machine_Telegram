from __future__ import annotations
from pathlib import Path
import shutil,os

class CapacityPlanner:
    def __init__(self,root):self.root=Path(root)

    def snapshot(self,integrated):
        disk=shutil.disk_usage(self.root)
        db_mib=0.0
        for data in integrated.values():
            for k,v in data.get("metrics",{}).items():
                if "database_size_mib" in k and isinstance(v,(int,float)):db_mib+=float(v)
        managed=sum(1 for data in integrated.values() if data.get("metrics",{}).get("auto_restart")==1)
        return {
            "disk_free_gib":round(disk.free/(1024**3),2),
            "disk_total_gib":round(disk.total/(1024**3),2),
            "known_database_mib":round(db_mib,2),
            "managed_runtime_services":managed,
            "cpu_capacity":"not_measured_without_platform_cpu_telemetry",
            "memory_capacity":"not_measured_without_platform_memory_telemetry",
            "recommendation":"No CPU/memory scaling claim is made until those metrics are measured."
        }
