from __future__ import annotations

class DigitalTwin:
    def build(self,integrated,code):
        nodes=[
            {"id":"Windows","type":"host"},
            {"id":"VM_Core","type":"platform"},
            {"id":"Telegram","type":"external"},
            {"id":"VM_Intelligence","type":"intelligence"},
        ]
        edges=[
            {"from":"VM_Intelligence","to":"VM_Core","type":"observes"},
            {"from":"VM_Core","to":"Windows","type":"runs_on"},
            {"from":"VM_Intelligence","to":"Windows","type":"runs_on"},
        ]
        for source,data in integrated.items():
            if source=="VM_Platform":continue
            nodes.append({"id":source,"type":"bot","available":data.get("available")})
            edges.append({"from":source,"to":"VM_Core","type":"uses_platform"})
            if source in {"Smart_Auto_Poster_V2","VM_Relationship_Manager","Universal_Search","Admin_Command_Centre"}:
                edges.append({"from":source,"to":"Telegram","type":"uses"})
            edges.append({"from":"VM_Intelligence","to":source,"type":"observes"})
        for m in code.get("nodes",[]):
            nodes.append({"id":m["id"],"type":"module","bot":m["bot"]})
            edges.append({"from":m["bot"],"to":m["id"],"type":"contains"})
        for e in code.get("edges",[]):
            target=e.get("to","")
            if target.startswith("shared.vm_core"):
                edges.append({"from":e["from"],"to":"VM_Core","type":"imports"})
            elif target.startswith("shared.vm_intelligence"):
                edges.append({"from":e["from"],"to":"VM_Intelligence","type":"imports"})
        # Deduplicate while keeping the model compact.
        seen=set();clean=[]
        for e in edges:
            key=(e["from"],e["to"],e["type"])
            if key not in seen:seen.add(key);clean.append(e)
        return {"nodes":nodes,"edges":clean,
                "note":"Operational digital twin built from current source/runtime evidence; it is a dependency model, not a perfect simulator."}
