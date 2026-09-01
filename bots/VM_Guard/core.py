
import re, time
from collections import defaultdict, deque
from urllib.parse import urlparse

SCAM_PHRASES = [
    "guaranteed profit","guaranteed returns","send crypto","double your money",
    "investment opportunity","wallet verification","seed phrase","recovery phrase",
]
SHORTENERS={"bit.ly","tinyurl.com","t.co","cutt.ly","rb.gy"}
URL_RE=re.compile(r"https?://[^\s]+",re.I)

def extract_domains(text:str):
    out=[]
    for url in URL_RE.findall(text or ""):
        try:
            d=(urlparse(url).hostname or "").lower()
            if d.startswith("www."): d=d[4:]
            if d: out.append(d)
        except: pass
    return out

def score_message(text:str):
    t=(text or "").lower()
    score=0; reasons=[]
    hits=[p for p in SCAM_PHRASES if p in t]
    if hits: score += min(60,30+10*len(hits)); reasons.append("scam language")
    domains=extract_domains(text)
    if any(d in SHORTENERS for d in domains): score+=20; reasons.append("shortened link")
    if t.count("http://")+t.count("https://")>=3: score+=15; reasons.append("many links")
    if len(t)>20 and sum(c.isupper() for c in text)/max(1,sum(c.isalpha() for c in text))>0.75:
        score+=10; reasons.append("excessive capitals")
    return min(score,100), reasons

class FloodTracker:
    def __init__(self, window=10, limit=6):
        self.window=window; self.limit=limit; self.events=defaultdict(deque)
    def hit(self, chat_id,user_id,now=None):
        now=time.time() if now is None else now
        q=self.events[(chat_id,user_id)]
        q.append(now)
        while q and q[0] < now-self.window: q.popleft()
        return len(q)>self.limit, len(q)
