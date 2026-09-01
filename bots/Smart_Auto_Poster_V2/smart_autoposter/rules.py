from __future__ import annotations

import json
from typing import Any

from .db import Database, utcnow

ALLOWED_CONDITIONS = {
    'tags_any','tags_all','tags_none','mode','access','forum','enabled','needs_review','protected','never_auto_post'
}
ALLOWED_ACTIONS = {
    'min_interval_seconds','preferred_account','protect','enable','never_auto_post','add_tags','remove_tags','quiet_start','quiet_end'
}


def _tags(v) -> set[str]:
    if isinstance(v, str):
        v = v.replace(';', ',').split(',')
    return {str(x).strip().lower() for x in (v or []) if str(x).strip()}


def validate_rule_payload(condition: dict[str, Any], action: dict[str, Any]) -> None:
    unknown_c = set(condition) - ALLOWED_CONDITIONS
    unknown_a = set(action) - ALLOWED_ACTIONS
    if unknown_c:
        raise ValueError('Unsupported rule condition(s): ' + ', '.join(sorted(unknown_c)))
    if unknown_a:
        raise ValueError('Unsupported rule action(s): ' + ', '.join(sorted(unknown_a)))
    if 'mode' in condition and condition['mode'] not in {'photo','text'}:
        raise ValueError('condition mode must be photo/text')
    if 'access' in condition and condition['access'] not in {'primary','secondary','both','any'}:
        raise ValueError('condition access must be primary/secondary/both/any')
    if 'preferred_account' in action and action['preferred_account'] not in {'primary','secondary','both'}:
        raise ValueError('preferred_account must be primary/secondary/both')
    if 'min_interval_seconds' in action and int(action['min_interval_seconds']) < 0:
        raise ValueError('min_interval_seconds cannot be negative')
    if ('quiet_start' in action) ^ ('quiet_end' in action):
        raise ValueError('quiet_start and quiet_end must be supplied together')


def upsert_rule(db: Database, rule_id: str, name: str, condition: dict, action: dict, *, priority: int = 100, enabled: bool = True) -> dict:
    rid = rule_id.strip().lower()
    if not rid:
        raise ValueError('rule_id cannot be empty')
    validate_rule_payload(condition, action)
    now = utcnow()
    with db.connect() as con:
        con.execute('''INSERT INTO automation_rules(rule_id,name,priority,enabled,condition_json,action_json,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(rule_id) DO UPDATE SET name=excluded.name,priority=excluded.priority,
                       enabled=excluded.enabled,condition_json=excluded.condition_json,action_json=excluded.action_json,updated_at=excluded.updated_at''',
                    (rid, name.strip() or rid, int(priority), int(enabled), json.dumps(condition, sort_keys=True), json.dumps(action, sort_keys=True), now, now))
        row = con.execute('SELECT * FROM automation_rules WHERE rule_id=?', (rid,)).fetchone()
    return dict(row)


def list_rules(db: Database, enabled_only: bool = False) -> list[dict]:
    where = 'WHERE enabled=1' if enabled_only else ''
    with db.connect() as con:
        rows = con.execute(f'SELECT * FROM automation_rules {where} ORDER BY priority,rule_id').fetchall()
    out=[]
    for r in rows:
        d=dict(r); d['condition']=json.loads(d.pop('condition_json')); d['action']=json.loads(d.pop('action_json')); out.append(d)
    return out


def _matches(dest: dict, tags: set[str], cond: dict) -> bool:
    if _tags(cond.get('tags_any')) and not (_tags(cond.get('tags_any')) & tags): return False
    if _tags(cond.get('tags_all')) and not _tags(cond.get('tags_all')).issubset(tags): return False
    if _tags(cond.get('tags_none')) and (_tags(cond.get('tags_none')) & tags): return False
    if cond.get('mode') and dest.get('mode') != cond['mode']: return False
    if 'forum' in cond and bool(dest.get('forum')) != bool(cond['forum']): return False
    if 'enabled' in cond and bool(dest.get('enabled')) != bool(cond['enabled']): return False
    if 'needs_review' in cond and bool(dest.get('needs_review')) != bool(cond['needs_review']): return False
    if 'protected' in cond and bool(dest.get('protected')) != bool(cond['protected']): return False
    if 'never_auto_post' in cond and bool(dest.get('never_auto_post')) != bool(cond['never_auto_post']): return False
    access=cond.get('access')
    if access == 'primary' and not dest.get('primary_access'): return False
    if access == 'secondary' and not dest.get('secondary_access'): return False
    if access == 'both' and not (dest.get('primary_access') and dest.get('secondary_access')): return False
    if access == 'any' and not (dest.get('primary_access') or dest.get('secondary_access')): return False
    return True


def evaluate_rule(db: Database, rule_id: str) -> list[int]:
    rules=[r for r in list_rules(db) if r['rule_id']==rule_id]
    if not rules:
        raise RuntimeError(f'Unknown rule: {rule_id}')
    rule=rules[0]
    with db.connect() as con:
        out=[]
        for r in con.execute('SELECT * FROM destinations ORDER BY group_id').fetchall():
            tags={x[0].lower() for x in con.execute('SELECT tag FROM destination_tags WHERE group_id=?',(r['group_id'],)).fetchall()}
            if _matches(dict(r), tags, rule['condition']): out.append(int(r['group_id']))
    return out


def apply_rules(db: Database, *, rule_id: str | None = None, actor: str = 'rules-engine', dry_run: bool = False) -> dict:
    rules=list_rules(db, enabled_only=True)
    if rule_id:
        rules=[r for r in rules if r['rule_id']==rule_id]
        if not rules: raise RuntimeError(f'Unknown/enabled rule: {rule_id}')
    matched=changed=0; by_rule={}
    with db.connect() as con:
        dests=[dict(r) for r in con.execute('SELECT * FROM destinations ORDER BY group_id').fetchall()]
        tags_by={d['group_id']:{x[0].lower() for x in con.execute('SELECT tag FROM destination_tags WHERE group_id=?',(d['group_id'],)).fetchall()} for d in dests}
        for rule in rules:
            rm=rc=0
            for d in dests:
                tags=tags_by[d['group_id']]
                if not _matches(d,tags,rule['condition']): continue
                matched+=1; rm+=1
                a=rule['action']; updates={}
                if 'min_interval_seconds' in a: updates['min_interval_seconds']=int(a['min_interval_seconds'])
                if 'preferred_account' in a:
                    wanted=a['preferred_account']
                    if wanted=='primary' and not d['primary_access'] and d['secondary_access']: wanted='secondary'
                    if wanted=='secondary' and not d['secondary_access'] and d['primary_access']: wanted='primary'
                    updates['preferred_account']=wanted
                if 'protect' in a: updates['protected']=int(bool(a['protect']))
                if 'never_auto_post' in a:
                    updates['never_auto_post']=int(bool(a['never_auto_post']))
                    if a['never_auto_post']: updates['enabled']=0
                if 'enable' in a:
                    # Never auto-enable unreviewed or hard-blocked destinations.
                    wanted=bool(a['enable']) and not d['needs_review'] and not (a.get('never_auto_post',d['never_auto_post']))
                    updates['enabled']=int(wanted)
                if 'quiet_start' in a and 'quiet_end' in a:
                    updates['quiet_start']=a['quiet_start']; updates['quiet_end']=a['quiet_end']
                add=_tags(a.get('add_tags')); remove=_tags(a.get('remove_tags'))
                state_changed=any(d.get(k)!=v for k,v in updates.items()) or bool(add-tags or remove & tags)
                if state_changed: rc+=1; changed+=1
                if not dry_run:
                    if updates:
                        updates['updated_at']=utcnow(); cols=list(updates)
                        con.execute('UPDATE destinations SET '+','.join(f'{k}=?' for k in cols)+' WHERE group_id=?',[updates[k] for k in cols]+[d['group_id']])
                        d.update(updates)
                    for t in add:
                        con.execute('INSERT OR IGNORE INTO destination_tags(group_id,tag) VALUES(?,?)',(d['group_id'],t)); tags.add(t)
                    for t in remove:
                        if not t.startswith('auto_'):
                            con.execute('DELETE FROM destination_tags WHERE group_id=? AND tag=?',(d['group_id'],t)); tags.discard(t)
            by_rule[rule['rule_id']]={'matched':rm,'changed':rc}
            if not dry_run:
                con.execute('UPDATE automation_rules SET last_applied_at=?,updated_at=? WHERE rule_id=?',(utcnow(),utcnow(),rule['rule_id']))
    if not dry_run and changed:
        db.audit(actor,'automation_rules_apply',target_type='rules',details=json.dumps({'matched':matched,'changed':changed,'by_rule':by_rule}))
    return {'dry_run':dry_run,'rules':len(rules),'matched':matched,'changed':changed,'by_rule':by_rule}
