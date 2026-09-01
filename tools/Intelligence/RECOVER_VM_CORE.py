from __future__ import annotations
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile, time, zipfile
from dataclasses import dataclass, asdict
from pathlib import Path

BOT_TARGETS=("Admin_Command_Centre","Universal_Search","VM_Guard")
BASE_REQUIRED={"__init__.py","admins.py","db.py","services.py","manifests.py","supervisor.py"}
OPTIONAL_EXPECTED=set()

PREFERRED_SNAPSHOT_PATTERNS=(
    ("pre_v1_4_3_ecosystem*",98),
    ("pre_v1_4_2_ecosystem*",96),
    ("pre_v1_4_1_ecosystem*",94),
)
MAX_FALLBACK_DIRS=1800
MAX_FALLBACK_ZIPS=240
MAX_FALLBACK_SECONDS=25.0

def progress(message:str)->None:
    print(f"[VMCORE] {message}",flush=True)
KNOWN_RELEASE_HASHES={
    "VM_Ecosystem_v1.4.0_DIRECT_DROP.zip":"fb845efd8d579d3155cc5af62b3b9e01071eb5ae7046a4371b0edaad06fae528",
    "VM_Ecosystem_v1.4.1_DIRECT_DROP.zip":"c3f54661a3727c8f73d1742e720ccdc138bd9e9e726d1a2e050f5c91606dbf86",
    "VM_Platform_v1.4.1_INCREMENTAL.zip":"a6e5ae78b39f501f88ffe155282ef159a1622535e5c246fb9e0dd3670abafd3e",
    "VM_Ecosystem_v1.4.2_MAINTENANCE.zip":"e9dbab60d5abbc7b1015c4fd47d16667b481abc1b9321abb211a151b532746db",
    "VM_Ecosystem_v1.4.3_MAINTENANCE.zip":"68a692d27811de27fc11b5392e8da378aa7dceea9bc693d38675b562c113c2a2",
}
SKIP_PARTS={"venv",".venv","__pycache__","node_modules","sessions","runtime","logs","data","database","databases","media","content",".pytest_cache",".git","backups"}
UNSAFE_SUFFIX={".env",".session",".sqlite",".sqlite3",".db",".pfx",".pem",".key"}

@dataclass
class Candidate:
    kind:str
    source:str
    trust:int
    label:str
    official_hash_ok:bool=False
    git_ref:str|None=None


def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def tree_fingerprint(path:Path)->tuple[str,int]:
    """Stable SHA-256 over relative path + contents for recovered VM Core provenance."""
    h=hashlib.sha256(); count=0
    for p in sorted((x for x in path.rglob('*') if x.is_file()), key=lambda x:x.as_posix().casefold()):
        if any(part.lower()=='__pycache__' for part in p.parts) or p.suffix.lower() in {'.pyc','.pyo'}:
            continue
        rel=p.relative_to(path).as_posix()
        h.update(rel.encode('utf-8')); h.update(b'\0')
        with p.open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''):
                h.update(block)
        h.update(b'\0'); count += 1
    return h.hexdigest(),count

def safe_tree(path:Path)->tuple[bool,str]:
    for p in path.rglob('*'):
        if p.is_symlink():
            return False,f"symlink not allowed in VM Core recovery candidate: {p.name}"
        if not p.is_file():continue
        if any(part.lower()=='__pycache__' for part in p.parts) or p.suffix.lower() in {'.pyc','.pyo'}:continue
        low=p.name.lower()
        if low in {'.env'} or p.suffix.lower() in UNSAFE_SUFFIX:
            return False,f"unsafe file in VM Core candidate: {p.name}"
        if p.suffix.lower() not in {'.py','.json','.txt','.md','.toml','.ini','.cfg'}:
            return False,f"unexpected binary/non-source file in VM Core candidate: {p.name}"
    return True,"ok"

def required_from_bot_imports(root:Path)->set[str]:
    req=set(BASE_REQUIRED)
    import re
    pat=re.compile(r"(?:from\s+shared\.vm_core\.([A-Za-z0-9_]+)|import\s+shared\.vm_core\.([A-Za-z0-9_]+))")
    for bot in BOT_TARGETS:
        b=root/'bots'/bot
        if not b.is_dir():continue
        for p in b.rglob('*.py'):
            if any(x.lower() in SKIP_PARTS or x.lower() in {'archive','backups'} for x in p.parts):continue
            try:t=p.read_text(encoding='utf-8-sig',errors='ignore')
            except Exception:continue
            for a,c in pat.findall(t):
                mod=a or c
                if mod:req.add(mod+'.py')
    return req


def preferred_snapshot_candidates(root:Path)->list[Candidate]:
    out=[];seen=set();backups=root/'backups'
    if not backups.is_dir():
        return out
    for pattern,trust in PREFERRED_SNAPSHOT_PATTERNS:
        try:
            parents=sorted(backups.glob(pattern),key=lambda p:p.name.casefold(),reverse=True)
        except Exception:
            parents=[]
        for parent in parents:
            vm=parent/'shared'/'vm_core'
            if not (vm/'__init__.py').is_file():
                continue
            try:key=str(vm.resolve()).casefold()
            except Exception:key=str(vm).casefold()
            if key in seen:continue
            seen.add(key)
            out.append(Candidate('directory',str(vm),trust,f"preferred snapshot {parent.name}"))
    return out


def shallow_local_candidates(root:Path)->list[Candidate]:
    """Cheap project-local lookup before any recursive or external scan."""
    out=[];seen=set()
    bases=[root/'backups',root/'archive',root/'releases',root/'state'/'recovery_candidates']
    patterns=("*/shared/vm_core","*/*/shared/vm_core")
    for base in bases:
        if not base.is_dir():continue
        for pattern in patterns:
            try:matches=sorted(base.glob(pattern),key=lambda p:p.as_posix().casefold())
            except Exception:matches=[]
            for vm in matches:
                if not (vm/'__init__.py').is_file():continue
                try:key=str(vm.resolve()).casefold()
                except Exception:key=str(vm).casefold()
                if key in seen:continue
                seen.add(key)
                low=str(vm).lower()
                trust=88 if any(x in low for x in ('backup','recovery','snapshot','archive')) else 70
                out.append(Candidate('directory',str(vm),trust,f"shallow local snapshot {vm.parent.parent.name}"))
    return out

def known_release_zip_candidates(root:Path)->list[Candidate]:
    home=Path.home()
    bases=[
        root/'releases', root/'archive', root/'backups',
        home/'Downloads', home/'Desktop', home/'OneDrive'/'Desktop'
    ]
    out=[];seen=set()
    for name,expected in KNOWN_RELEASE_HASHES.items():
        for base in bases:
            if not base.exists():continue
            # Exact filename lookups first; one directory level under backup/release roots is allowed.
            paths=[base/name]
            if base in {root/'releases',root/'archive',root/'backups'}:
                try:paths += list(base.glob(f"*/{name}"))
                except Exception:pass
            for z in paths:
                if not z.is_file():continue
                try:key=str(z.resolve()).casefold()
                except Exception:key=str(z).casefold()
                if key in seen:continue
                seen.add(key)
                try:actual=sha256(z)
                except Exception:continue
                if actual.lower()!=expected.lower():
                    progress(f"Rejected known release with unexpected hash: {z.name}")
                    continue
                try:
                    with zipfile.ZipFile(z) as arc:
                        names=[n.replace('\\','/') for n in arc.namelist()]
                        if not any(n.lower().endswith('/shared/vm_core/__init__.py') or n.lower()=='shared/vm_core/__init__.py' for n in names):
                            continue
                except Exception:continue
                out.append(Candidate('zip',str(z),100,f"verified official release {z.name}",official_hash_ok=True))
    return out

def bounded_fallback_candidates(root:Path, *, external:bool=False)->list[Candidate]:
    """Last-resort bounded scan. It cannot walk indefinitely across OneDrive/history."""
    started=time.monotonic();dirs_seen=0;zips_seen=0;out=[];seen=set()
    if external:
        roots=[Path.home()/'Downloads',Path.home()/'OneDrive'/'Desktop']
        local=os.environ.get('LOCALAPPDATA')
        if local:roots.append(Path(local)/'Vending_Machine_Telegram'/'recovery_backups')
    else:
        roots=[
            root/'backups',root/'archive',root/'releases',root/'updates'/'backups',
            root/'state'/'support',root/'state'/'recovery_candidates'
        ]
    current=(root/'shared'/'vm_core').resolve()
    for base in roots:
        if time.monotonic()-started>=MAX_FALLBACK_SECONDS or dirs_seen>=MAX_FALLBACK_DIRS:
            break
        if not base.exists() or not base.is_dir():continue
        progress(f"Fallback scan: {base}")
        try:
            for dirpath,dirs,files in os.walk(base):
                dirs_seen += 1
                p=Path(dirpath)
                try:depth=len(p.relative_to(base).parts) if p!=base else 0
                except Exception:depth=99
                dirs[:]=[d for d in dirs if d.lower() not in SKIP_PARTS and d.lower() not in {'.git','runtime','logs'}]
                if depth>6:dirs[:]=[]
                if time.monotonic()-started>=MAX_FALLBACK_SECONDS or dirs_seen>=MAX_FALLBACK_DIRS:
                    dirs[:]=[]
                    break
                if p.name=='vm_core' and p.parent.name=='shared' and '__init__.py' in files:
                    try:rp=p.resolve()
                    except Exception:rp=p
                    if rp!=current:
                        key=('directory',str(rp).casefold())
                        if key not in seen:
                            seen.add(key)
                            low=str(rp).lower()
                            trust=85 if any(x in low for x in ('backup','recovery','snapshot','archive')) else 60
                            out.append(Candidate('directory',str(rp),trust,f"fallback directory {rp}"))
                    dirs[:]=[]
                if zips_seen<MAX_FALLBACK_ZIPS:
                    for name in files:
                        if not name.lower().endswith('.zip'):continue
                        zips_seen += 1
                        if zips_seen>MAX_FALLBACK_ZIPS:break
                        z=p/name
                        key=('zip',str(z).casefold())
                        if key in seen:continue
                        seen.add(key)
                        known=KNOWN_RELEASE_HASHES.get(z.name)
                        official=False
                        if known:
                            try:official=sha256(z).lower()==known.lower()
                            except Exception:official=False
                            if not official:continue
                        try:
                            with zipfile.ZipFile(z) as arc:
                                names=[n.replace('\\','/') for n in arc.namelist()]
                                if not any(n.lower().endswith('/shared/vm_core/__init__.py') or n.lower()=='shared/vm_core/__init__.py' for n in names):
                                    continue
                        except Exception:continue
                        trust=100 if official else (80 if any(x in str(z).lower() for x in ('backup','recovery','snapshot','archive')) else 65)
                        out.append(Candidate('zip',str(z),trust,f"fallback zip {z.name}",official_hash_ok=official))
        except Exception:
            continue
    progress(f"{'External' if external else 'Project-local'} fallback bounded at dirs={dirs_seen}, zips={zips_seen}, seconds={time.monotonic()-started:.1f}")
    return out

def scan_dirs(root:Path,search_roots:list[Path])->list[Candidate]:
    out=[];seen=set()
    current=(root/'shared'/'vm_core').resolve()
    for base in search_roots:
        if not base or not base.exists() or not base.is_dir():continue
        try:
            for dirpath,dirs,files in os.walk(base):
                p=Path(dirpath)
                # Keep scans bounded and skip huge/noisy trees.
                rel_depth=len(p.relative_to(base).parts) if p!=base else 0
                dirs[:]=[d for d in dirs if d.lower() not in SKIP_PARTS and d.lower() not in {'.git','runtime','logs'}]
                if rel_depth>8:
                    dirs[:]=[];continue
                if p.name=='vm_core' and p.parent.name=='shared' and '__init__.py' in files:
                    rp=p.resolve()
                    if rp==current:continue
                    key=str(rp).casefold()
                    if key in seen:continue
                    seen.add(key)
                    low=str(rp).lower()
                    if 'pre_v1_4_3_ecosystem' in low: trust=98
                    elif 'pre_v1_4_2_ecosystem' in low: trust=96
                    elif 'pre_v1_4_1_ecosystem' in low: trust=94
                    elif any(x in low for x in ('backup','recovery','snapshot','archive')): trust=85
                    else: trust=60
                    out.append(Candidate('directory',str(rp),trust,f"local directory {rp}"))
                    dirs[:]=[]
        except Exception:continue
    return out

def scan_zips(search_roots:list[Path])->list[Candidate]:
    out=[];seen=set()
    for base in search_roots:
        if not base or not base.exists():continue
        files=[]
        if base.is_file() and base.suffix.lower()=='.zip':files=[base]
        elif base.is_dir():
            try:
                # Common release/backup ZIPs are shallow; cap recursion through os.walk.
                for dirpath,dirs,names in os.walk(base):
                    p=Path(dirpath);depth=len(p.relative_to(base).parts) if p!=base else 0
                    dirs[:]=[d for d in dirs if d.lower() not in SKIP_PARTS and d.lower() not in {'.git','runtime','logs'}]
                    if depth>6:dirs[:]=[];continue
                    files.extend(p/n for n in names if n.lower().endswith('.zip'))
            except Exception:pass
        for z in files:
            try:key=str(z.resolve()).casefold()
            except Exception:key=str(z).casefold()
            if key in seen:continue
            seen.add(key)
            known=KNOWN_RELEASE_HASHES.get(z.name)
            official=False
            if known:
                try:official=(sha256(z).lower()==known.lower())
                except Exception:official=False
                if not official:continue  # fail closed on a known release name with wrong bytes
            try:
                with zipfile.ZipFile(z) as arc:
                    names=[n.replace('\\','/') for n in arc.namelist()]
                    if not any(n.lower().endswith('/shared/vm_core/__init__.py') or n.lower()=='shared/vm_core/__init__.py' for n in names):
                        continue
            except Exception:continue
            trust=100 if official else (80 if any(x in str(z).lower() for x in ('backup','recovery','snapshot','archive')) else 65)
            out.append(Candidate('zip',str(z),trust,f"zip {z.name}",official_hash_ok=official))
    return out

def git_candidates(root:Path)->list[Candidate]:
    if not (root/'.git').exists():return []
    try:
        r=subprocess.run(['git','-C',str(root),'rev-list','--all','--','shared/vm_core/__init__.py'],capture_output=True,text=True,timeout=15)
        if r.returncode!=0:return []
        refs=[x.strip() for x in r.stdout.splitlines() if x.strip()][:20]
        return [Candidate('git',str(root),90-i, f"git commit {ref[:12]}", git_ref=ref) for i,ref in enumerate(refs)]
    except Exception:return []

def extract_zip_vm_core(z:Path,dest:Path)->Path|None:
    with zipfile.ZipFile(z) as arc:
        names=[n.replace('\\','/') for n in arc.namelist()]
        anchors=[]
        for n in names:
            low=n.lower()
            needle='shared/vm_core/__init__.py'
            if low.endswith(needle):anchors.append(n[:-len('__init__.py')])
        if not anchors:return None
        # Prefer the shallowest complete vm_core path.
        anchors.sort(key=lambda x:(x.count('/'),len(x)))
        prefix=anchors[0]
        vm=dest/'vm_core';vm.mkdir(parents=True,exist_ok=True)
        for original,norm in zip(arc.namelist(),names):
            if not norm.startswith(prefix):continue
            rel=norm[len(prefix):]
            if not rel or rel.endswith('/'):continue
            rel_path=Path(rel)
            if rel_path.is_absolute() or '..' in rel_path.parts or (rel_path.parts and ':' in rel_path.parts[0]):
                raise ValueError(f"unsafe ZIP path in VM Core candidate: {rel}")
            target=vm/rel_path
            resolved_target=target.resolve()
            if vm.resolve() not in resolved_target.parents:
                raise ValueError(f"ZIP path escapes VM Core staging directory: {rel}")
            if any(part.lower()=='__pycache__' for part in target.parts) or target.suffix.lower() in {'.pyc','.pyo'}:continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with arc.open(original) as src,target.open('wb') as dst:shutil.copyfileobj(src,dst)
        return vm

def materialize(c:Candidate,dest:Path)->Path|None:
    if dest.exists():shutil.rmtree(dest)
    dest.mkdir(parents=True)
    if c.kind=='directory':
        target=dest/'vm_core';shutil.copytree(Path(c.source),target,ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pyo'),symlinks=True);return target
    if c.kind=='zip':return extract_zip_vm_core(Path(c.source),dest)
    if c.kind=='git':
        archive=dest/'git.zip'
        r=subprocess.run(['git','-C',c.source,'archive','--format=zip','-o',str(archive),c.git_ref,'shared/vm_core'],capture_output=True,text=True)
        if r.returncode!=0:return None
        return extract_zip_vm_core(archive,dest)
    return None

def compile_candidate(vm:Path)->tuple[bool,str]:
    cache=vm.parent/'pycache'
    env=os.environ.copy();env['PYTHONPYCACHEPREFIX']=str(cache)
    r=subprocess.run([sys.executable,'-m','compileall','-q',str(vm)],capture_output=True,text=True,env=env)
    shutil.rmtree(cache,ignore_errors=True)
    return r.returncode==0,(r.stdout+r.stderr)[-4000:]

def import_candidate(vm:Path,required:set[str])->tuple[bool,str]:
    stage=vm.parent/'import_stage';shutil.rmtree(stage,ignore_errors=True)
    (stage/'shared').mkdir(parents=True)
    (stage/'shared'/'__init__.py').write_text('',encoding='utf-8')
    shutil.copytree(vm,stage/'shared'/'vm_core')
    mods=['shared.vm_core.'+x[:-3] for x in sorted(required) if x!='__init__.py']
    code="import importlib,sys; sys.path.insert(0,r'%s'); mods=%r; [importlib.import_module(x) for x in mods]; print('IMPORT_OK')"%(str(stage),mods)
    r=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=30)
    return r.returncode==0,(r.stdout+r.stderr)[-6000:]

def discover_suite(root:Path,package_root:Path,bot:str)->dict:
    tool=package_root/'tools'/'Intelligence'/'DISCOVER_BOT_TESTS.py'
    r=subprocess.run([sys.executable,str(tool),'--root',str(root),'--bot',bot],capture_output=True,text=True)
    if r.returncode!=0:return {'available':False,'reason':'discovery_failed','stderr':r.stderr[-1000:]}
    try:return json.loads(r.stdout)
    except Exception:return {'available':False,'reason':'discovery_json_failed','stdout':r.stdout[-1000:]}

def run_bot_suite(root:Path,package_root:Path,bot:str)->tuple[bool,dict]:
    d=discover_suite(root,package_root,bot)
    if not d.get('available'):
        return False,{'bot':bot,'ok':False,'reason':d.get('reason')}
    cmd=[sys.executable,str(package_root/'tools'/'Intelligence'/'RUN_TEST_SUITE.py'),
         '--root',str(root),'--suite-root',d['suite_root'],'--test-dir',d['test_dir'],'--bot-root',str(root/'bots'/bot)]
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=180)
    return r.returncode==0,{'bot':bot,'ok':r.returncode==0,'returncode':r.returncode,'reason':d.get('reason'),
                           'stdout_tail':r.stdout[-3000:],'stderr_tail':r.stderr[-3000:]}

def validate_live(root:Path,package_root:Path)->tuple[bool,list[dict]]:
    results=[]
    for bot in BOT_TARGETS:
        ok,row=run_bot_suite(root,package_root,bot);results.append(row)
        if not ok:return False,results
    # If platform tests still exist, run them as an additional acceptance gate, excluding Intelligence tests.
    platform_tests=root/'tests'
    if platform_tests.is_dir():
        test_files=[p for p in platform_tests.glob('test_*.py') if p.is_file()]
        if test_files:
            cmd=[sys.executable,'-m','unittest']+[p.stem for p in test_files]
            env=os.environ.copy();env['PYTHONPATH']=str(root)+os.pathsep+env.get('PYTHONPATH','')
            r=subprocess.run(cmd,cwd=platform_tests,capture_output=True,text=True,env=env,timeout=180)
            row={'bot':'VM_Platform','ok':r.returncode==0,'returncode':r.returncode,'tests':len(test_files),
                 'stdout_tail':r.stdout[-3000:],'stderr_tail':r.stderr[-3000:]}
            results.append(row)
            if r.returncode!=0:return False,results
    return True,results

def copy_candidate_to_root(vm:Path,root:Path):
    dest=root/'shared'/'vm_core'
    if dest.exists():shutil.rmtree(dest)
    dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(vm,dest,ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pyo'))
    shared_init=root/'shared'/'__init__.py'
    if not shared_init.exists():shared_init.write_text('# Vending Machine Telegram shared package.\n',encoding='utf-8')

def write_report(path:Path,payload:dict):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(payload,indent=2,default=str),encoding='utf-8')
    txt=path.with_suffix('.txt')
    lines=['VM CORE RECOVERY RESULT','='*72,f"Status: {payload.get('status')}",f"Required files: {', '.join(payload.get('required_files',[]))}"]
    if payload.get('accepted'):
        a=payload['accepted'];lines += [f"Accepted: {a.get('label')}",f"Source: {a.get('source')}",f"Kind: {a.get('kind')}"]
    lines += ['', 'Candidates tried:']
    for x in payload.get('attempts',[]):lines.append(f"- {x.get('label')} | {x.get('result')} | {x.get('reason','')}")
    txt.write_text('\n'.join(lines)+'\n',encoding='utf-8')

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--package-root',required=True);p.add_argument('--report',required=True)
    a=p.parse_args(argv);root=Path(a.root).resolve();package_root=Path(a.package_root).resolve();report=Path(a.report).resolve()
    required=required_from_bot_imports(root)|OPTIONAL_EXPECTED
    external_scan_enabled=os.environ.get("VM_CORE_RECOVERY_SKIP_EXTERNAL","0").strip().lower() not in {"1","true","yes"}
    progress("Recovery search started.")
    candidate_groups=[
        ("preferred snapshots", preferred_snapshot_candidates(root)),
        ("shallow project-local snapshots", shallow_local_candidates(root)),
        ("known verified releases", known_release_zip_candidates(root)),
        ("Git history", git_candidates(root)),
    ]
    # Generic fallback is intentionally deferred until all high-provenance candidates fail.
    payload={'status':'not_found','root':str(root),'required_files':sorted(required),'candidates_found':0,'attempts':[],'accepted':None}
    work=Path(tempfile.mkdtemp(prefix='vm_core_recovery_'))
    target=root/'shared'/'vm_core'
    shared_init=root/'shared'/'__init__.py'
    shared_init_existed=shared_init.exists()
    original_backup=None
    try:
        if target.exists():
            original_backup=work/'original_vm_core';shutil.copytree(target,original_backup)
        idx=0
        seen_candidates=set()
        groups_iter=list(candidate_groups)
        groups_iter.append(("bounded project-local fallback", "project"))
        if external_scan_enabled:
            groups_iter.append(("bounded external fallback", "external"))
        else:
            progress("External fallback disabled by explicit test/diagnostic environment flag.")
        for group_name,group_candidates in groups_iter:
            if group_candidates == "project":
                progress("No shallow/high-provenance candidate passed. Starting bounded project-local fallback.")
                group_candidates=bounded_fallback_candidates(root,external=False)
            elif group_candidates == "external":
                progress("No project-local candidate passed. Starting bounded external fallback.")
                group_candidates=bounded_fallback_candidates(root,external=True)
            # Deduplicate this stage against prior stages while preserving stage priority.
            staged=[]
            for c in sorted(group_candidates,key=lambda x:(-x.trust,x.label.casefold())):
                key=(c.kind,c.source.casefold(),c.git_ref or '')
                if key in seen_candidates:continue
                seen_candidates.add(key);staged.append(c)
            payload['candidates_found'] += len(staged)
            progress(f"{group_name}: {len(staged)} candidate(s).")
            for c in staged:
                row=asdict(c);row['result']='rejected';row['reason']=''
                progress(f"Testing candidate trust={c.trust}: {c.label}")
                try:
                    vm=materialize(c,work/f'candidate_{idx}')
                    if not vm or not vm.is_dir():row['reason']='materialization_failed';payload['attempts'].append(row);progress(f"Rejected: {row['reason']}");idx+=1;continue
                    missing=[f for f in sorted(required) if not (vm/f).is_file()]
                    if missing:row['reason']='missing_required:'+','.join(missing);payload['attempts'].append(row);progress(f"Rejected: {row['reason']}");idx+=1;continue
                    safe,why=safe_tree(vm)
                    if not safe:row['reason']=why;payload['attempts'].append(row);progress(f"Rejected: {row['reason']}");idx+=1;continue
                    ok,why=compile_candidate(vm)
                    if not ok:row['reason']='compile_failed:'+why[-500:];payload['attempts'].append(row);progress(f"Rejected: {row['reason']}");idx+=1;continue
                    ok,why=import_candidate(vm,required)
                    if not ok:row['reason']='isolated_import_failed:'+why[-800:];payload['attempts'].append(row);progress(f"Rejected: {row['reason']}");idx+=1;continue
                    copy_candidate_to_root(vm,root)
                    ok,tests=validate_live(root,package_root)
                    row['tests']=tests
                    if not ok:
                        shutil.rmtree(target,ignore_errors=True)
                        if original_backup:shutil.copytree(original_backup,target)
                        if not shared_init_existed: shared_init.unlink(missing_ok=True)
                        row['reason']='live_regression_gate_failed';payload['attempts'].append(row);progress(f"Rejected: {row['reason']}");idx+=1;continue
                    digest,file_count=tree_fingerprint(target)
                    row['result']='accepted';row['reason']='compile_import_and_regression_gates_passed'
                    row['recovered_tree_sha256']=digest
                    row['recovered_file_count']=file_count
                    progress(f"Accepted VM Core candidate: {c.label}")
                    payload['attempts'].append(row);payload['accepted']=row;payload['status']='recovered'
                    write_report(report,payload)
                    audit=root/'state'/'vm_core_recovery.json'
                    audit.parent.mkdir(parents=True,exist_ok=True)
                    audit.write_text(json.dumps(payload,indent=2,default=str),encoding='utf-8')
                    print(json.dumps({
                        'status':'recovered',
                        'source':row['source'],
                        'kind':row['kind'],
                        'trust':row['trust'],
                        'official_hash_ok':row['official_hash_ok'],
                        'recovered_tree_sha256':row['recovered_tree_sha256'],
                        'recovered_file_count':row['recovered_file_count'],
                        'report':str(report)
                    },default=str));return 0
                except Exception as exc:
                    row['reason']=f"{type(exc).__name__}:{exc}";payload['attempts'].append(row)
                    shutil.rmtree(target,ignore_errors=True)
                    if original_backup and not target.exists():shutil.copytree(original_backup,target)
                    if not shared_init_existed: shared_init.unlink(missing_ok=True)
                    progress(f"Rejected with exception: {row['reason']}");idx+=1
        if not shared_init_existed: shared_init.unlink(missing_ok=True)
        payload['status']='no_acceptable_candidate';write_report(report,payload)
        print(json.dumps({
            'status':'no_acceptable_candidate',
            'candidates_found':payload['candidates_found'],
            'attempts':len(payload['attempts']),
            'report':str(report)
        },default=str));return 4
    finally:
        shutil.rmtree(work,ignore_errors=True)

if __name__=='__main__':raise SystemExit(main())
