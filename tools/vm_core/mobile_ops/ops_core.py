from __future__ import annotations
import re

LINE = re.compile(r"^([A-Za-z0-9_+-]+)\s+(RUNNING|STOPPED|DISABLED)\s+(\d*)\s*(.*)$")

def parse_status(text: str) -> list[dict]:
    rows=[]
    for raw in text.splitlines():
        line=raw.strip()
        m=LINE.match(line)
        if not m:
            continue
        rows.append({"bot":m.group(1),"state":m.group(2),"processes":int(m.group(3) or 0),"launcher":m.group(4).strip()})
    return rows

def status_summary(text: str) -> str:
    rows=parse_status(text)
    if not rows:
        return "Could not parse VM status."
    icon={"RUNNING":"âœ…","STOPPED":"âŒ","DISABLED":"â¸"}
    lines=["ðŸ¤– VM STATUS"]
    for r in rows:
        lines.append(f"{icon.get(r['state'],'â€¢')} {r['bot']}: {r['state']}")
    return "\n".join(lines)

def offline_names(text: str) -> list[str]:
    return [r["bot"] for r in parse_status(text) if r["state"]=="STOPPED"]
