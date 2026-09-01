from __future__ import annotations

from database import Database, utcnow


class PrivacyEngine:
    def __init__(self, db: Database): self.db=db

    def control(self,telegram_id:int):
        return self.db.one('SELECT * FROM contact_controls WHERE telegram_id=?',(telegram_id,))

    def is_excluded(self,telegram_id:int)->bool:
        r=self.control(telegram_id)
        return bool(r and r['excluded'])

    def is_archived(self,telegram_id:int)->bool:
        r=self.control(telegram_id)
        return bool(r and r['archived'])

    def set_excluded(self,telegram_id:int,excluded:bool,reason:str=''):
        old=self.control(telegram_id)
        archived=old['archived'] if old else 0
        self.db.execute(
            """INSERT INTO contact_controls(telegram_id,archived,excluded,reason,updated_at)
               VALUES (?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
               excluded=excluded.excluded,reason=excluded.reason,updated_at=excluded.updated_at""",
            (telegram_id,archived,1 if excluded else 0,reason or None,utcnow()))
        return self.control(telegram_id)

    def set_archived(self,telegram_id:int,archived:bool,reason:str=''):
        old=self.control(telegram_id)
        excluded=old['excluded'] if old else 0
        self.db.execute(
            """INSERT INTO contact_controls(telegram_id,archived,excluded,reason,updated_at)
               VALUES (?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
               archived=excluded.archived,reason=excluded.reason,updated_at=excluded.updated_at""",
            (telegram_id,1 if archived else 0,excluded,reason or None,utcnow()))
        return self.control(telegram_id)

    def forget_behavior(self,telegram_id:int):
        self.db.execute('DELETE FROM private_interactions WHERE telegram_id=?',(telegram_id,))
        self.db.execute('DELETE FROM behavior_metrics WHERE telegram_id=?',(telegram_id,))

    def purge_contact(self,telegram_id:int):
        # Contacts cascade most relationship data via FK. Control row has no FK.
        self.db.execute('DELETE FROM contacts WHERE telegram_id=?',(telegram_id,))
        self.db.execute('DELETE FROM contact_controls WHERE telegram_id=?',(telegram_id,))

    def summary(self):
        contacts=self.db.one('SELECT COUNT(*) n FROM contacts')['n']
        private_events=self.db.one('SELECT COUNT(*) n FROM private_interactions')['n']
        excluded=self.db.one('SELECT COUNT(*) n FROM contact_controls WHERE excluded=1')['n']
        archived=self.db.one('SELECT COUNT(*) n FROM contact_controls WHERE archived=1')['n']
        return {'contacts':contacts,'private_metadata_events':private_events,'excluded':excluded,'archived':archived}
