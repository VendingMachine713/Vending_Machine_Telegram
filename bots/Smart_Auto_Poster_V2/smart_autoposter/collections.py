from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .db import Database, utcnow


def _tags(value: str | None) -> set[str]:
    return {x.strip().lower() for x in (value or '').replace(';', ',').split(',') if x.strip()}


@dataclass(frozen=True)
class CollectionSpec:
    collection_id: str
    name: str
    include_tags: str = ''
    exclude_tags: str = ''
    required_access: str = 'any'
    mode: str = 'any'
    forum_only: bool = False
    include_protected: bool = False
    enabled: bool = True


def upsert_collection(db: Database, spec: CollectionSpec) -> dict:
    cid = spec.collection_id.strip().lower()
    if not cid:
        raise ValueError('collection_id cannot be empty')
    access = spec.required_access.strip().lower()
    mode = spec.mode.strip().lower()
    if access not in {'any','primary','secondary','both'}:
        raise ValueError('required_access must be any/primary/secondary/both')
    if mode not in {'any','photo','text'}:
        raise ValueError('mode must be any/photo/text')
    now = utcnow()
    with db.connect() as con:
        con.execute('''INSERT INTO destination_collections(collection_id,name,include_tags,exclude_tags,required_access,mode,
                       forum_only,include_protected,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(collection_id) DO UPDATE SET name=excluded.name,include_tags=excluded.include_tags,
                       exclude_tags=excluded.exclude_tags,required_access=excluded.required_access,mode=excluded.mode,
                       forum_only=excluded.forum_only,include_protected=excluded.include_protected,enabled=excluded.enabled,
                       updated_at=excluded.updated_at''',
                    (cid, spec.name.strip() or cid, ','.join(sorted(_tags(spec.include_tags))), ','.join(sorted(_tags(spec.exclude_tags))),
                     access, mode, int(spec.forum_only), int(spec.include_protected), int(spec.enabled), now, now))
    return get_collection(db, cid)


def get_collection(db: Database, collection_id: str) -> dict:
    with db.connect() as con:
        row = con.execute('SELECT * FROM destination_collections WHERE collection_id=?', (collection_id.strip().lower(),)).fetchone()
    if not row:
        raise RuntimeError(f'Unknown destination collection: {collection_id}')
    return dict(row)


def list_collections(db: Database, enabled_only: bool = False) -> list[dict]:
    where = 'WHERE enabled=1' if enabled_only else ''
    with db.connect() as con:
        return [dict(r) for r in con.execute(f'SELECT * FROM destination_collections {where} ORDER BY collection_id').fetchall()]


def delete_collection(db: Database, collection_id: str) -> None:
    cid = collection_id.strip().lower()
    with db.connect() as con:
        ref = con.execute("SELECT campaign_id FROM campaigns WHERE ','||lower(target_collections)||',' LIKE ? LIMIT 1", (f'%,{cid},%',)).fetchone()
        if ref:
            raise RuntimeError(f'Collection is referenced by campaign: {ref[0]}')
        con.execute('DELETE FROM destination_collections WHERE collection_id=?', (cid,))


def destination_matches_collection(dest: dict, dest_tags: Iterable[str], collection: dict) -> bool:
    tags = {str(x).strip().lower() for x in dest_tags if str(x).strip()}
    include = _tags(collection.get('include_tags'))
    exclude = _tags(collection.get('exclude_tags'))
    if include and not include.intersection(tags):
        return False
    if exclude and exclude.intersection(tags):
        return False
    if bool(dest.get('never_auto_post')):
        return False
    if bool(dest.get('protected')) and not bool(collection.get('include_protected')):
        return False
    access = (collection.get('required_access') or 'any').lower()
    if access == 'primary' and not bool(dest.get('primary_access')):
        return False
    if access == 'secondary' and not bool(dest.get('secondary_access')):
        return False
    if access == 'both' and not (bool(dest.get('primary_access')) and bool(dest.get('secondary_access'))):
        return False
    if access == 'any' and not (bool(dest.get('primary_access')) or bool(dest.get('secondary_access'))):
        return False
    mode = (collection.get('mode') or 'any').lower()
    if mode != 'any' and (dest.get('mode') or '').lower() != mode:
        return False
    if bool(collection.get('forum_only')) and not bool(dest.get('forum')):
        return False
    return True


def resolve_collection(db: Database, collection_id: str) -> list[dict]:
    collection = get_collection(db, collection_id)
    if not collection['enabled']:
        return []
    with db.connect() as con:
        rows = con.execute("SELECT * FROM destinations WHERE enabled=1 AND needs_review=0 AND mode IN ('photo','text') ORDER BY group_name").fetchall()
        out = []
        for r in rows:
            tags = [x[0] for x in con.execute('SELECT tag FROM destination_tags WHERE group_id=?', (r['group_id'],)).fetchall()]
            d = dict(r)
            if destination_matches_collection(d, tags, collection):
                out.append(d)
    return out


def collection_preview(db: Database, collection_id: str) -> dict:
    c = get_collection(db, collection_id)
    rows = resolve_collection(db, collection_id)
    return {
        'collection_id': c['collection_id'],
        'name': c['name'],
        'enabled': bool(c['enabled']),
        'selected': len(rows),
        'group_ids': [int(x['group_id']) for x in rows],
        'primary_only': sum(1 for x in rows if x['primary_access'] and not x['secondary_access']),
        'secondary_only': sum(1 for x in rows if x['secondary_access'] and not x['primary_access']),
        'both': sum(1 for x in rows if x['secondary_access'] and x['primary_access']),
        'photo': sum(1 for x in rows if x['mode'] == 'photo'),
        'text': sum(1 for x in rows if x['mode'] == 'text'),
    }
