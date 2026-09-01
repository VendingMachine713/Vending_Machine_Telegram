from __future__ import annotations
from pathlib import Path
import json

class KnowledgeInventory:
    """Builds a secrets-safe structural inventory of the VM project."""
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def snapshot(self) -> dict:
        bots_dir = self.root/"bots"
        bots = []
        if bots_dir.exists():
            for p in sorted(x for x in bots_dir.iterdir() if x.is_dir()):
                bots.append({
                    "name": p.name,
                    "has_main": (p/"main.py").exists(),
                    "has_requirements": (p/"requirements.txt").exists(),
                    "has_env_template": (p/".env.example").exists(),
                })
        return {"bots": bots, "bot_count": len(bots)}
