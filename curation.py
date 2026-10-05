"""Local editorial admission. Candidates never call AI; reservations survive retries.

A daily place is reserved before inference, so failures and restarts cannot spend
it again. Similarity is conservative lexical matching, never a factual verdict.
"""
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from database import connect, utcnow, setting
from story_groups import words, timestamp

DAILY_LIMIT=80
PUBLISHER_LIMIT=8
PRAGUE=ZoneInfo('Europe/Prague')
EVERGREEN={'goodnewsnetwork.org','positive.news','optimistdaily.com','goodgoodgood.co','reasonstobecheerful.world'}

def publisher(value):
    host=urlsplit(value if '://' in (value or '') else 'https://'+(value or '')).hostname or 'unknown'
    parts=host.lower().rstrip('.').split('.')
    host='.'.join(parts[-3:] if '.'.join(parts[-2:]) in ('co.uk','com.au','co.nz') else parts[-2:])
    return 'bbc.com' if host in ('bbc.co.uk','bbci.co.uk','bbc.com') else host


def score(item,now):
    age=max(0,(now.timestamp()-timestamp(item['published_at']))/3600)
    return min(1,len(item.get('excerpt','').split())/100)+max(0,1-age/48)


def same_event(a,b):
    ta,tb=words(a.get('title')),words(b.get('title'))
    da,db=timestamp(a.get('published_at')),timestamp(b.get('published_at'))
    if da is None or db is None or abs(da-db)>6*3600 or min(len(ta),len(tb))<5:return False
    if {w for w in ta if w.isdigit()}!={w for w in tb if w.isdigit()}:return False
    if set(re.findall(r'\b(?:nie|not|bez|no)\b',a.get('title','').casefold())) != set(re.findall(r'\b(?:nie|not|bez|no)\b',b.get('title','').casefold())):return False
    overlap=len(ta & tb)
    ea,eb=words(a.get('excerpt')),words(b.get('excerpt'))
    if ta==tb and (not ea or not eb):return len(ta)>=6
    return overlap>=5 and overlap/max(1,len(ta|tb))>=.75 and min(len(ea),len(eb))>=8 and len(ea&eb)/max(1,len(ea|eb))>=.55


def read_payload(row,now):
    try:
        item=json.loads(row['payload'])
        if not isinstance(item,dict) or not all(isinstance(item.get(k),str) and item[k] for k in ('id','title','canonical_url','published_at')):return None,'invalid_candidate'
        date=timestamp(item['published_at'])
        if date is None or date>now.timestamp()+300:return None,'invalid_candidate_date'
        if row['id']!=item['id']:return None,'invalid_candidate'
        if not isinstance(item.get('excerpt',''),str):return None,'invalid_candidate'
        item['excerpt']=item.get('excerpt','')[:6000]
        item['publisher']=publisher(row['source_name'] or item['canonical_url'])
        window=7*86400 if item['publisher'] in EVERGREEN else 48*3600
        if now.timestamp()-date>window:return None,'selection_too_old'
        item['bucket']=item.get('category') or 'Ostatné';item['score']=score(item,now)
        return item,None
    except (ValueError,TypeError,KeyError):return None,'invalid_candidate'


def publish_aliases(connection=None):
    """Deferred source links become public only once the representative exists."""
    if connection is None:
        with connect() as c:return publish_aliases(c)
    rows=connection.execute('''SELECT t.payload,coalesce(a.id,al.article_id) representative_id FROM editorial_links l
        JOIN tasks t ON t.id=l.candidate_id JOIN tasks rep ON rep.id=l.representative_id
        LEFT JOIN clanky a ON a.id=rep.id LEFT JOIN article_aliases al ON al.url=json_extract(rep.payload,'$.canonical_url')
        WHERE rep.state='done' AND coalesce(a.id,al.article_id) IS NOT NULL''').fetchall()
    for row in rows:
        item=json.loads(row['payload'])
        connection.execute('INSERT OR IGNORE INTO article_aliases VALUES(?,?,?,?)',
            (row['representative_id'],item.get('source_id'),item['canonical_url'],item['title']))
    return len(rows)


def select_candidates(now=None):
    if setting('pipeline_paused','0')=='1' or setting('quota_until','')>utcnow():return 0
    now=(now or datetime.now(timezone.utc)).astimezone(PRAGUE)
    stamp=now.astimezone(timezone.utc).isoformat(timespec='seconds');day=now.date().isoformat()
    allowance=math.floor(DAILY_LIMIT*(now.hour//2+1)/12)
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute("INSERT OR IGNORE INTO settings VALUES('editorial_started_at',?)",(stamp,))
        # Only unreserved, unprocessed jobs are admitted; no archive is rewritten.
        c.execute("UPDATE tasks SET state='candidate',error=NULL WHERE kind='article' AND state='pending' AND NOT EXISTS(SELECT 1 FROM editorial_reservations r WHERE r.task_id=tasks.id)")
        # Unfinished prior-day places are re-admitted under today's allowance.
        c.execute("UPDATE tasks SET state='candidate' WHERE state='pending' AND id IN (SELECT task_id FROM editorial_reservations WHERE day<?)",(day,))
        # A failed representative does not permanently swallow another source.
        c.execute("UPDATE tasks SET state='candidate',error=NULL WHERE state='duplicate' AND id IN (SELECT l.candidate_id FROM editorial_links l JOIN tasks t ON t.id=l.representative_id WHERE t.state IN ('failed','skipped'))")
        c.execute("DELETE FROM editorial_links WHERE candidate_id IN (SELECT id FROM tasks WHERE state='candidate')")
        rows=c.execute("SELECT t.*,s.name source_name FROM tasks t LEFT JOIN sources s ON s.id=json_extract(CASE WHEN json_valid(t.payload) THEN t.payload ELSE '{}' END,'$.source_id') WHERE t.kind='article' AND t.state='candidate' AND (t.available_at IS NULL OR t.available_at<=?) ORDER BY t.created_at,t.id",(stamp,)).fetchall()
        candidates=[]
        for row in rows:
            item,error=read_payload(row,now)
            if error:c.execute("UPDATE tasks SET state='skipped',error=?,updated_at=? WHERE id=?",(error,stamp,row['id']))
            else:candidates.append(item)
        known=[]
        for row in c.execute("SELECT t.*,s.name source_name FROM tasks t LEFT JOIN sources s ON s.id=json_extract(CASE WHEN json_valid(t.payload) THEN t.payload ELSE '{}' END,'$.source_id') WHERE t.kind='article' AND (t.state IN ('pending','processing') OR (t.state='done' AND EXISTS(SELECT 1 FROM clanky a WHERE a.id=t.id)))"):
            item,error=read_payload(row,now)
            if item:known.append(item)
            elif row['state']=='pending' and error=='selection_too_old':
                c.execute("UPDATE tasks SET state='skipped',error=?,updated_at=? WHERE id=?",(error,stamp,row['id']))
        def duplicate(item,representative):
            c.execute('INSERT OR REPLACE INTO editorial_links VALUES(?,?,?)',(item['id'],representative['id'],stamp))
            c.execute("UPDATE tasks SET state='duplicate',error='selection_duplicate',updated_at=? WHERE id=?",(stamp,item['id']))
        groups=[]
        for item in sorted(candidates,key=lambda x:(-x['score'],x['id'])):
            leader=next((old for old in known if same_event(item,old)),None)
            if leader:duplicate(item,leader);continue
            group=next((g for g in groups if same_event(item,g[0])),None)
            if group is None:groups.append([item])
            else:group.append(item)
        reservations=c.execute('SELECT publisher,bucket FROM editorial_reservations WHERE day=?',(day,)).fetchall()
        publishers=Counter(r['publisher'] for r in reservations);topics=Counter(r['bucket'] for r in reservations)
        selected=0;remaining=max(0,allowance-len(reservations))
        while groups and remaining:
            eligible=[g for g in groups if publishers[g[0]['publisher']]<PUBLISHER_LIMIT]
            if not eligible:break
            # Diversity is evaluated after every pick, not only within one RSS feed.
            group=max(eligible,key=lambda g:(g[0]['score']-publishers[g[0]['publisher']]*2-topics[g[0]['bucket']]*.7,g[0]['published_at'],g[0]['id']))
            item=group[0]
            c.execute('INSERT INTO editorial_reservations VALUES(?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET day=excluded.day,publisher=excluded.publisher,bucket=excluded.bucket,score=excluded.score,selected_at=excluded.selected_at',(item['id'],day,item['publisher'],item['bucket'],item['score'],stamp))
            c.execute("UPDATE tasks SET state='pending',error=NULL,updated_at=? WHERE id=?",(stamp,item['id']))
            for alias in group[1:]:duplicate(alias,item)
            publishers[item['publisher']]+=1;topics[item['bucket']]+=1;selected+=1;remaining-=1;groups.remove(group)
        for group in groups:
            reason='selection_publisher_limit' if publishers[group[0]['publisher']]>=PUBLISHER_LIMIT else 'selection_waiting_slot'
            for item in group:c.execute('UPDATE tasks SET error=?,updated_at=? WHERE id=? AND error IS NOT ?',(reason,stamp,item['id'],reason))
        publish_aliases(c)
        c.execute("INSERT OR REPLACE INTO settings VALUES('last_editorial_selection',?)",(stamp,))
    return selected


def editorial_status(connection,now=None):
    now=(now or datetime.now(timezone.utc)).astimezone(PRAGUE);day=now.date().isoformat()
    return {'day':day,'limit':DAILY_LIMIT,'publisher_limit':PUBLISHER_LIMIT,
        'allowance':math.floor(DAILY_LIMIT*(now.hour//2+1)/12),
        'selected':connection.execute('SELECT count(*) FROM editorial_reservations WHERE day=?',(day,)).fetchone()[0],
        'states':dict(connection.execute("SELECT state,count(*) FROM tasks WHERE state IN ('candidate','duplicate','skipped') GROUP BY state").fetchall())}
