from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json
from typing import Any
from .paths import project_root
from .manifests import discover_bots
SKIP_NAMES={'.env'}; SKIP_SUFFIXES={'.session','.session-journal','.pyc'}
def _sha(p:Path)->str:
    h=hashlib.sha256();
    with p.open('rb') as f:
        for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
    return h.hexdigest()
def analyze_nested_duplicates(root:Path|None=None)->dict[str,Any]:
    root=root or project_root(); report={'schema_version':2,'generated_at_utc':datetime.now(timezone.utc).isoformat(),'bots':[]}
    for bot in discover_bots(root):
        if not bot.nested_duplicate_folder: continue
        outer=Path(bot.path); nested=outer/bot.folder; rows=[]
        for np in sorted(nested.rglob('*')):
            if not np.is_file(): continue
            rel=np.relative_to(nested)
            if np.name.lower() in SKIP_NAMES or np.suffix.lower() in SKIP_SUFFIXES:
                rows.append({'relative_path':rel.as_posix(),'status':'SENSITIVE_SKIPPED','nested_size':np.stat().st_size}); continue
            op=outer/rel; nh=_sha(np)
            if not op.is_file(): rows.append({'relative_path':rel.as_posix(),'status':'NESTED_ONLY','nested_size':np.stat().st_size,'nested_sha256':nh}); continue
            oh=_sha(op); same=nh==oh
            rows.append({'relative_path':rel.as_posix(),'status':'EXACT_DUPLICATE' if same else 'DIFFERENT','nested_size':np.stat().st_size,'outer_size':op.stat().st_size,'nested_sha256':nh,'outer_sha256':oh})
        st=[x['status'] for x in rows]; safe=bool(rows) and all(x=='EXACT_DUPLICATE' for x in st)
        report['bots'].append({'bot':bot.folder,'nested_folder':str(nested),'safe_exact_duplicate_only':safe,'summary':{s:st.count(s) for s in sorted(set(st))},'files':rows,'recommendation':'Eligible for manual review before deletion; every compared file is identical.' if safe else 'Preserve folder. Merge DIFFERENT/NESTED_ONLY files deliberately before any cleanup.'})
    return report
def write_duplicate_report(root:Path|None=None):
    root=root or project_root(); data=analyze_nested_duplicates(root); out=root/'diagnostics'; out.mkdir(parents=True,exist_ok=True); jp=out/'duplicate_analysis.json'; tp=out/'duplicate_analysis.txt'; jp.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8'); lines=['='*72,'VM NESTED DUPLICATE ANALYSIS','='*72,f"Generated: {data['generated_at_utc']}",'']
    if not data['bots']: lines.append('No nested duplicate bot folders detected.')
    for item in data['bots']:
        lines += [f"[{item['bot']}]",f"nested_folder={item['nested_folder']}",f"safe_exact_duplicate_only={item['safe_exact_duplicate_only']}",f"summary={item['summary']}",f"recommendation={item['recommendation']}"]
        lines += [f"  {row['status']:<18} {row['relative_path']}" for row in item['files']]; lines.append('')
    tp.write_text('\n'.join(lines)+'\n',encoding='utf-8'); return jp,tp
