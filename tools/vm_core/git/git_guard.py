#!/usr/bin/env python3
from __future__ import annotations
import argparse, math, re, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

TOKEN_PATTERNS = [
    ("Telegram bot token", re.compile(r"\b\d{7,12}:[A-Za-z0-9_-]{30,}\b")),
    ("Private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b")),
]

SENSITIVE_NAMES = [
    re.compile(r"(^|/)\.env($|\.)", re.I),
    re.compile(r"\.session(?:-journal)?$", re.I),
    re.compile(r"\.(?:pem|p12|pfx|key)$", re.I),
    re.compile(r"(^|/)(?:credentials?|secrets?)(?:\.|/|$)", re.I),
]

SAFE_EXAMPLE_NAMES = {".env.example", ".env.template", ".env.sample"}
MAX_BYTES = 2_000_000

LITERAL_ASSIGNMENT = re.compile(
    r'''(?im)^\s*(?:BOT_TOKEN|TELEGRAM_TOKEN|API_HASH|PASSWORD|SECRET_KEY|INTERNAL_API_KEY|GH_TOKEN|GITHUB_TOKEN)\s*[:=]\s*(["'])([^"'\r\n]+)\1'''
)

PLACEHOLDERS = {
    "", "changeme", "change-me", "replace-me", "replace_me",
    "your_token_here", "your-token-here", "example", "placeholder",
    "<token>", "<secret>", "<bot_token>", "<api_hash>",
    "bot_token_here", "api_hash_here", "your_bot_token", "your_api_hash",
}

def run_git(*args: str):
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True)

def candidates(staged: bool) -> list[str]:
    if staged:
        cp = run_git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    else:
        cp = run_git("ls-files", "--cached", "--others", "--exclude-standard")
    return [x.strip() for x in cp.stdout.splitlines() if x.strip()]

def is_binary(data: bytes) -> bool:
    return b"\x00" in data[:4096]

def entropy(s: str) -> float:
    if not s:
        return 0.0
    from collections import Counter
    c = Counter(s)
    n = len(s)
    return -sum((v/n)*math.log2(v/n) for v in c.values())

def looks_like_secret_literal(value: str) -> bool:
    v = value.strip()
    lv = v.lower()
    if lv in PLACEHOLDERS:
        return False
    if any(x in lv for x in ("getenv(", "environ[", "config.", "settings.", "${", "{{", "os.")):
        return False
    compact = re.sub(r"\s+", "", v)
    return len(compact) >= 24 and entropy(compact) >= 3.4

def scan(paths: list[str]) -> list[tuple[str,str]]:
    findings=[]
    for rel in paths:
        rel_norm=rel.replace("\\","/")
        name=Path(rel_norm).name
        if name not in SAFE_EXAMPLE_NAMES:
            for pat in SENSITIVE_NAMES:
                if pat.search(rel_norm):
                    findings.append((rel, "Sensitive filename must stay ignored"))
                    break

        p=ROOT/rel
        try:
            if not p.is_file() or p.stat().st_size > MAX_BYTES:
                continue
            data=p.read_bytes()
            if is_binary(data):
                continue
            text=data.decode("utf-8", errors="ignore")
        except OSError:
            continue

        for label,pat in TOKEN_PATTERNS:
            if pat.search(text):
                findings.append((rel,label))

        for m in LITERAL_ASSIGNMENT.finditer(text):
            value=m.group(2).strip()
            if looks_like_secret_literal(value):
                findings.append((rel,"High-entropy literal assigned to secret-like variable"))

    out=[]; seen=set()
    for item in findings:
        if item not in seen:
            out.append(item); seen.add(item)
    return out

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--staged", action="store_true")
    args=ap.parse_args()
    paths=candidates(args.staged)
    findings=scan(paths)
    if findings:
        print("[BLOCKED] Secret guard found files requiring review:")
        for path,why in findings:
            print(f" - {path}: {why}")
        print("No secret values are printed.")
        return 2
    print(f"[PASS] Secret guard: {len(paths)} trackable file(s) checked; no obvious secrets found.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
