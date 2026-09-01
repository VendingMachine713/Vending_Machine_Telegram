from __future__ import annotations
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json, urllib.parse, urllib.request

def _env(path,name):
    if not path.is_file():return None
    try:
        for raw in path.read_text(encoding="utf-8-sig",errors="ignore").splitlines():
            if "=" not in raw or raw.lstrip().startswith("#"):continue
            k,v=raw.split("=",1)
            if k.strip()==name:return v.strip().strip('"').strip("'")
    except Exception:pass
    return None

class TelegramNotifier:
    def __init__(self,store,root):
        self.store=store;self.root=Path(root)
        self.cfg=self._config()

    def _config(self):
        path=self.root/"config"/"vm_intelligence.json"
        defaults={"enabled":True,"daily_brief":True,"weekly_review":True,
                  "timezone":"Australia/Adelaide","daily_hour":8,"weekly_weekday":0}
        try:
            if path.is_file():defaults.update(json.loads(path.read_text(encoding="utf-8-sig")))
        except Exception:pass
        return defaults

    def _credentials(self):
        bot=self.root/"bots"/"Admin_Command_Centre"
        candidates=[bot/".env",*sorted(bot.glob("**/.env"),key=lambda p:len(p.parts))]
        token=None;ids=set()
        for p in candidates:
            token=token or _env(p,"VM_ADMIN_BOT_TOKEN")
            raw=_env(p,"VM_ADMIN_USER_IDS") or ""
            for x in raw.replace(";",",").split(","):
                try:
                    if x.strip():ids.add(int(x.strip()))
                except Exception:pass
        try:
            from shared.vm_core.admins import load_admin_ids
            ids.update(load_admin_ids(self.root))
        except Exception:pass
        return token,sorted(ids)

    def _state(self,key):
        with self.store.connect() as con:
            r=con.execute("SELECT state_value FROM notification_state WHERE state_key=?",(key,)).fetchone()
            return r[0] if r else None

    def _set(self,key,value):
        from datetime import datetime,timezone
        now=datetime.now(timezone.utc).isoformat()
        with self.store.connect() as con:
            con.execute("""INSERT INTO notification_state(state_key,state_value,updated_at_utc)
                VALUES(?,?,?) ON CONFLICT(state_key) DO UPDATE SET
                state_value=excluded.state_value,updated_at_utc=excluded.updated_at_utc""",(key,value,now))

    def _send(self,text):
        if not self.cfg.get("enabled"):return 0
        token,ids=self._credentials()
        if not token or not ids:return 0
        sent=0
        for uid in ids:
            try:
                data=urllib.parse.urlencode({"chat_id":uid,"text":text[:3900]}).encode()
                req=urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",data=data)
                with urllib.request.urlopen(req,timeout=15) as r:
                    if 200<=r.status<300:sent+=1
            except Exception:
                pass
        return sent

    def notify(self,snapshot):
        now=datetime.now(ZoneInfo(self.cfg.get("timezone","Australia/Adelaide")))
        sent=[]
        priority=[x for x in snapshot.get("inbox",[]) if x.get("priority") in {"P0","P1"}]
        fingerprint="|".join(sorted(
            f"{x.get('priority')}:{x.get('source')}:{x.get('title')}" for x in priority))
        if priority and self._state("attention_fingerprint")!=fingerprint:
            text="VM INTELLIGENCE ALERT\n\n"+"\n".join(
                f"[{x['priority']}] {x['source']}: {x['title']}" for x in priority[:8])
            n=self._send(text)
            if n:
                self._set("attention_fingerprint",fingerprint);sent.append("attention")
        elif not priority and self._state("attention_fingerprint"):
            self._set("attention_fingerprint","")
        day=now.date().isoformat()
        if self.cfg.get("daily_brief") and now.hour>=int(self.cfg.get("daily_hour",8)) and self._state("daily_day")!=day:
            sc=snapshot["scorecard"]
            rel=snapshot.get("reliability",{});aut=snapshot.get("autonomy",{})
            text=(f"VM DAILY BRIEF\nOverall: {sc['overall']}/100\n"
                  f"SLO compliance: {rel.get('compliance_pct','n/a')}% | breaches: {rel.get('breaches','n/a')}\n"
                  f"Autonomy: effective L{aut.get('effective_level',aut.get('level','?'))} {aut.get('effective_level_name',aut.get('level_name',''))}\n"
                  f"Incidents: {len(snapshot.get('incidents',[]))}\n"
                  f"Recommendations: {len(snapshot.get('recommendations',[]))}\n"
                  f"Goals missed: {sum(1 for g in snapshot.get('goals',[]) if g['status']=='missed')}\n"
                  f"User action: {'REVIEW' if priority else 'None'}")
            if self._send(text):
                self._set("daily_day",day);sent.append("daily")
        week=f"{now.isocalendar().year}-{now.isocalendar().week}"
        if self.cfg.get("weekly_review") and now.weekday()==int(self.cfg.get("weekly_weekday",0)) and now.hour>=int(self.cfg.get("daily_hour",8)) and self._state("weekly_week")!=week:
            text=(f"VM WEEKLY ENGINEERING REVIEW\nOverall: {snapshot['scorecard']['overall']}/100\n"
                  f"SLO compliance: {snapshot.get('reliability',{}).get('compliance_pct','n/a')}%\n"
                  f"Architecture hygiene: {snapshot.get('platform_normalization',{}).get('score','n/a')}/100\n"
                  f"Open incidents: {len(snapshot.get('incidents',[]))}\n"
                  f"Improvements: {len(snapshot.get('improvements',[]))}\n"
                  f"Automation opportunities: {len(snapshot.get('automation_opportunities',[]))}\n"
                  f"Technical-debt score: {snapshot.get('technical_debt',{}).get('debt_score','n/a')}")
            if self._send(text):
                self._set("weekly_week",week);sent.append("weekly")
        return sent
