from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from database import Database, utcnow


class QueryEngine:
    TYPE_WORDS = {
        'prospect','customer','regular','vip','supplier','vendor','partner',
        'admin','group_owner','unknown'
    }
    STATUS_WORDS = {'active','returned','cooling','dormant','new'}
    MOMENTUM_WORDS = {'growing','surging','stable','cooling','fading','learning'}

    def __init__(self, db: Database):
        self.db = db

    def search(self, query: str, limit: int = 30):
        tokens = query.strip().split()
        where = ['COALESCE(cc.excluded,0)=0', 'COALESCE(cc.archived,0)=0']
        params = []
        name_terms = []
        joins = (
            'LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id '
            'LEFT JOIN contact_intelligence i ON i.telegram_id=c.telegram_id '
            'LEFT JOIN behavior_metrics b ON b.telegram_id=c.telegram_id '
            'LEFT JOIN network_metrics n ON n.telegram_id=c.telegram_id '
            'LEFT JOIN contact_priorities p ON p.telegram_id=c.telegram_id '
            'LEFT JOIN contact_forecasts f ON f.telegram_id=c.telegram_id '
            'LEFT JOIN data_quality_metrics q ON q.telegram_id=c.telegram_id '
            'LEFT JOIN conversation_session_metrics s ON s.telegram_id=c.telegram_id '
            'LEFT JOIN contact_classifications x ON x.telegram_id=c.telegram_id '
            'LEFT JOIN classifier_calibration ca ON ca.relationship_type=x.predicted_type'
        )

        for raw in tokens:
            token = raw.strip()
            low = token.lower()

            if ':' in low:
                key, val = low.split(':', 1)
                if key == 'type':
                    where.append('c.relationship_type=?'); params.append(val)
                elif key == 'status':
                    where.append('c.activity_status=?'); params.append(val)
                elif key in {'verify','verification'}:
                    where.append('c.verification_status=?'); params.append(val)
                elif key == 'momentum':
                    where.append('i.momentum_label=?'); params.append(val)
                elif key in {'behavior','behaviour'}:
                    where.append('b.behavior_label=?'); params.append(val)
                elif key == 'network':
                    where.append('n.network_label=?'); params.append(val)
                elif key == 'tag':
                    where.append('EXISTS (SELECT 1 FROM tags t WHERE t.telegram_id=c.telegram_id AND t.tag LIKE ?)')
                    params.append(f'%{val}%')
                elif key == 'group':
                    where.append('EXISTS (SELECT 1 FROM contact_groups g WHERE g.telegram_id=c.telegram_id AND g.chat_id<0 AND COALESCE(g.chat_title,CAST(g.chat_id AS TEXT)) LIKE ?)')
                    params.append(f'%{val}%')
                elif key == 'segment':
                    where.append('EXISTS (SELECT 1 FROM contact_segments sg WHERE sg.telegram_id=c.telegram_id AND sg.segment_key=?)')
                    params.append(val)
                elif key in {'outlook','forecast'}:
                    where.append('f.outlook_label=?'); params.append(val)
                elif key == 'session':
                    where.append('s.session_label=?'); params.append(val)
                elif key in {'predicted','prediction'}:
                    where.append('x.predicted_type=?'); params.append(val)
                elif key == 'classstate':
                    where.append('x.decision_state=?'); params.append(val)
                elif key in {'calibration','calstate'}:
                    if val in {'quarantined','off','disabled'}:
                        where.append('COALESCE(ca.auto_enabled,1)=0')
                    elif val in {'auto','enabled','on'}:
                        where.append('COALESCE(ca.auto_enabled,1)=1')
                elif key == 'id' and val.isdigit():
                    where.append('c.telegram_id=?'); params.append(int(val))
                else:
                    name_terms.append(token)
                continue

            match = re.fullmatch(r'(health|score|trust|reach|bridge|priority|risk|confidence|completeness|sessions|classconfidence|action)(<=|>=|<|>|=)(-?\d+)', low)
            if match:
                key, op, num = match.groups()
                column = {
                    'health':'i.health_score', 'score':'c.relationship_score',
                    'trust':'c.trust_score', 'reach':'n.reach_score', 'bridge':'n.bridge_score', 'priority':'p.priority_score',
                    'risk':'f.disengagement_risk', 'confidence':'q.confidence_score',
                    'completeness':'q.completeness_score', 'sessions':'s.sessions_30',
                    'classconfidence':'x.confidence',
                    'action':"(SELECT COALESCE(MAX(ra.action_score),0) FROM recommended_actions ra WHERE ra.telegram_id=c.telegram_id AND ra.status IN ('open','snoozed'))"
                }[key]
                where.append(f'COALESCE({column},0) {op} ?')
                params.append(int(num))
                continue

            match = re.fullmatch(r'inactive(?:>|:)?(\d+)(?:d)?', low)
            if match:
                cutoff = (datetime.now(timezone.utc)-timedelta(days=int(match.group(1)))).isoformat()
                where.append('c.last_seen<?')
                params.append(cutoff)
                continue

            singular = low[:-1] if low.endswith('s') else low
            if singular in self.TYPE_WORDS:
                where.append('c.relationship_type=?'); params.append(singular); continue
            if low in self.STATUS_WORDS:
                where.append('c.activity_status=?'); params.append(low); continue
            if low in self.MOMENTUM_WORDS:
                where.append('i.momentum_label=?'); params.append(low); continue
            if low == 'unverified':
                where.append("c.verification_status IN ('unknown','pending')"); continue
            if low == 'overdue':
                where.append('COALESCE(i.days_overdue,0)>0'); continue
            if low == 'bridge':
                where.append('COALESCE(n.bridge_score,0)>=55'); continue
            if low == 'important':
                where.append('c.relationship_score>=60'); continue
            if low in {'atrisk','at_risk'}:
                where.append('COALESCE(f.disengagement_risk,0)>=55'); continue
            if low == 'lowconfidence':
                where.append('COALESCE(q.confidence_score,0)<50'); continue
            if low == 'classsuggested':
                where.append("x.decision_state='suggested'"); continue
            if low == 'exception':
                where.append("EXISTS (SELECT 1 FROM recommended_actions ra WHERE ra.telegram_id=c.telegram_id AND ra.status IN ('open','snoozed') AND ra.action_score>=50 AND (ra.cooldown_until IS NULL OR ra.cooldown_until<=?))"); params.append(utcnow()); continue
            if low in {'quarantined','classquarantined'}:
                where.append('COALESCE(ca.auto_enabled,1)=0'); continue
            if low in {'actionsuppressed','cooldown'}:
                where.append("EXISTS (SELECT 1 FROM recommended_actions ra WHERE ra.telegram_id=c.telegram_id AND ra.cooldown_until>?)"); params.append(utcnow()); continue
            if low == 'goaldue':
                where.append("EXISTS (SELECT 1 FROM relationship_goals rg WHERE rg.telegram_id=c.telegram_id AND rg.status='active' AND rg.target_at IS NOT NULL AND rg.target_at<=?)"); params.append(utcnow()); continue
            name_terms.append(token)

        if name_terms:
            q = '%' + ' '.join(name_terms).strip('@') + '%'
            where.append('(c.display_name LIKE ? COLLATE NOCASE OR c.username LIKE ? COLLATE NOCASE)')
            params.extend([q, q])

        sql = f"""
            SELECT c.*, i.health_score, i.momentum_label, i.lifecycle_stage, i.days_overdue,
                   b.reciprocity_score, b.behavior_label,
                   n.reach_score, n.bridge_score, n.network_label,
                   p.priority_score, p.priority_band, p.next_action,
                   f.disengagement_risk, f.outlook_label, f.confidence AS outlook_confidence,
                   q.completeness_score, q.confidence_score,
                   s.sessions_30, s.session_label,
                   x.predicted_type, x.confidence AS classification_confidence, x.decision_state AS classification_state,
                   ca.effective_threshold AS classification_auto_threshold, ca.auto_enabled AS classification_auto_enabled,
                   (SELECT COALESCE(MAX(ra.action_score),0) FROM recommended_actions ra WHERE ra.telegram_id=c.telegram_id AND ra.status IN ('open','snoozed')) AS max_action_score
            FROM contacts c
            {joins}
            WHERE {' AND '.join(where)}
            ORDER BY COALESCE(p.priority_score,0) DESC,
                     c.relationship_score DESC,
                     COALESCE(i.health_score,50) ASC,
                     c.last_seen DESC
            LIMIT ?
        """
        params.append(limit)
        return self.db.all(sql, params)

    def save_view(self, admin_id: int, name: str, query: str):
        name = name.strip().lower().replace(' ', '_')[:32]
        if not name or not query.strip():
            raise ValueError('View name and query are required.')
        self.db.execute(
            """INSERT INTO saved_views(admin_id,view_name,query_text,created_at,updated_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(admin_id,view_name) DO UPDATE SET
                 query_text=excluded.query_text,
                 updated_at=excluded.updated_at""",
            (admin_id, name, query.strip(), utcnow(), utcnow()),
        )
        return name

    def views(self, admin_id: int):
        return self.db.all(
            'SELECT * FROM saved_views WHERE admin_id=? ORDER BY view_name',
            (admin_id,),
        )

    def get_view(self, admin_id: int, name: str):
        return self.db.one(
            'SELECT * FROM saved_views WHERE admin_id=? AND view_name=?',
            (admin_id, name.strip().lower().replace(' ', '_')),
        )
