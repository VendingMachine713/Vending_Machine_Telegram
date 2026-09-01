from __future__ import annotations
from pathlib import Path
import argparse,hashlib,json,sys

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def verify(package_root: Path, manifest_path: Path) -> dict:
    data=json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_files=data.get("files") or {}
    missing=[];mismatch=[];collisions=[];unexpected=[]
    # Detect case-insensitive path collisions before hashing. This protects Windows extraction.
    case_seen={}
    actual=[]
    for p in package_root.rglob("*"):
        if not p.is_file() or p.resolve()==manifest_path.resolve():
            continue
        rel=p.relative_to(package_root).as_posix()
        actual.append(rel)
        key=rel.casefold()
        prev=case_seen.get(key)
        if prev is not None and prev!=rel:
            collisions.append([prev,rel])
        else:
            case_seen[key]=rel
    for rel,expected in sorted(expected_files.items()):
        p=package_root/rel
        if not p.is_file():
            missing.append(rel);continue
        actual_hash=sha256(p)
        if actual_hash.lower()!=str(expected).lower():
            mismatch.append({"file":rel,"expected":expected,"actual":actual_hash})
    unexpected=sorted(set(actual)-set(expected_files))
    ok=not missing and not mismatch and not collisions and not unexpected
    return {"ok":ok,"checked":len(expected_files),"missing":missing,"mismatch":mismatch,
            "case_collisions":collisions,"unexpected":unexpected}

def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument("--package-root",required=True)
    ap.add_argument("--manifest",required=True)
    a=ap.parse_args(argv)
    result=verify(Path(a.package_root).resolve(),Path(a.manifest).resolve())
    print(json.dumps(result))
    return 0 if result["ok"] else 2

if __name__=="__main__":
    raise SystemExit(main())
