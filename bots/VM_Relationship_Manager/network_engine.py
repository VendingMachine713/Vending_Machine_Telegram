from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

from database import Database, utcnow


class NetworkEngine:
    """Computes network value from already-observed Telegram group membership.

    Metrics are estimates over the Relationship Manager's known contact/group
    graph, not Telegram-wide social graph claims.
    """

    def __init__(self, db: Database):
        self.db=db

    def compute(self, telegram_id: int):
        groups=self.db.all(
            "SELECT chat_id, last_seen FROM contact_groups WHERE telegram_id=? AND chat_id<0",
            (telegram_id,),
        )
        group_ids={r['chat_id'] for r in groups}
        shared=len(group_ids)
        cutoff=(datetime.now(timezone.utc)-timedelta(days=30)).isoformat()
        active30=sum(1 for r in groups if r['last_seen']>=cutoff)

        all_rows=self.db.all("SELECT telegram_id, chat_id FROM contact_groups WHERE chat_id<0")
        group_to_contacts={}
        contact_to_groups={}
        for r in all_rows:
            group_to_contacts.setdefault(r['chat_id'],set()).add(r['telegram_id'])
            contact_to_groups.setdefault(r['telegram_id'],set()).add(r['chat_id'])

        neighbors=set()
        for gid in group_ids:
            neighbors |= group_to_contacts.get(gid,set())
        neighbors.discard(telegram_id)
        known_neighbors=len(neighbors)

        # Diversity estimates how different the audiences of this person's
        # shared groups are. Groups with little member overlap increase bridge value.
        pairs=[]
        gids=list(group_ids)
        for i in range(len(gids)):
            a=group_to_contacts.get(gids[i],set())
            for j in range(i+1,len(gids)):
                b=group_to_contacts.get(gids[j],set())
                union=len(a|b)
                jaccard=(len(a&b)/union) if union else 1.0
                pairs.append(1.0-jaccard)
        diversity=round(100*(sum(pairs)/len(pairs))) if pairs else (35 if shared==1 else 0)

        # Reach rewards multiple groups and unique known neighbours but caps
        # quickly so very large groups do not dominate everything.
        reach=round(min(100, 18*math.log2(1+shared) + 13*math.log2(1+known_neighbors))) if shared else 0
        bridge=round(min(100, (0.55*diversity)+(0.30*min(100,shared*14))+(0.15*min(100,known_neighbors*2)))) if shared else 0

        if shared==0:
            label='isolated'
        elif bridge>=75 and shared>=3:
            label='bridge'
        elif reach>=75:
            label='high_reach'
        elif shared>=3:
            label='multi_group'
        else:
            label='local'

        self.db.execute(
            """INSERT INTO network_metrics
               (telegram_id, shared_groups, active_groups_30, known_neighbors,
                reach_score, bridge_score, diversity_score, network_label, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(telegram_id) DO UPDATE SET
                 shared_groups=excluded.shared_groups,
                 active_groups_30=excluded.active_groups_30,
                 known_neighbors=excluded.known_neighbors,
                 reach_score=excluded.reach_score,
                 bridge_score=excluded.bridge_score,
                 diversity_score=excluded.diversity_score,
                 network_label=excluded.network_label,
                 computed_at=excluded.computed_at""",
            (telegram_id,shared,active30,known_neighbors,reach,bridge,diversity,label,utcnow()),
        )
        return self.db.one("SELECT * FROM network_metrics WHERE telegram_id=?",(telegram_id,))

    def get(self, telegram_id:int, refresh:bool=False):
        row=self.db.one("SELECT * FROM network_metrics WHERE telegram_id=?",(telegram_id,))
        if refresh or row is None:
            return self.compute(telegram_id)
        return row

    def compute_all(self):
        for r in self.db.all("SELECT telegram_id FROM contacts"):
            self.compute(r['telegram_id'])
