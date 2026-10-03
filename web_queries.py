"""Read-side queries: parameterized filters and literal FTS phrases."""
import json
import math
import hashlib
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlencode
from config import SENTIMENTS, TOPICS
from database import connect
from story_groups import group_articles, load_aliases

PAGE_SIZE = 30
# Full article bodies are unnecessary on public reading pages.
ARTICLE_COLUMNS = ','.join('a.'+name for name in ('id','nadpis','link','zhrnutie','sentiment','kategoria','povodny_nadpis','canonical_url','source_id','published_at','created_at','topic','region','tags','entities','sentiment_reason','source_scope'))

def reader_key(article_id):
    """Keep normal IDs; expose a bounded opaque reference for legacy RSS URL IDs."""
    return article_id if re.fullmatch(r'[A-Za-z0-9_-]{1,80}',article_id) else 'legacy-'+hashlib.sha256(article_id.encode('utf-8')).hexdigest()

def resolve_reader_ids(connection, ids):
    if not any(value.startswith('legacy-') for value in ids): return ids
    mapping = {reader_key(row[0]):row[0] for row in connection.execute("SELECT id FROM clanky WHERE length(id)>80 OR length(id)=0 OR id GLOB '*[^A-Za-z0-9_-]*'")}
    return [mapping.get(value,value) for value in ids]

def json_list(value):
    try:
        parsed = json.loads(value or '[]')
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []

def article(row):
    result = dict(row)
    result['reader_id'] = reader_key(result['id'])
    result['tags'] = json_list(result.get('tags'))
    result['entities'] = json_list(result.get('entities'))
    return result

def iso_date(value):
    try: return date.fromisoformat(value).isoformat() if value else ''
    except (ValueError, TypeError): return ''

def list_articles(args, archive=False, saved_ids=None):
    selected = args.getlist('sentiment') if 'filtered' in args or 'sentiment' in args else list(SENTIMENTS)
    selected = [s for s in selected if s in SENTIMENTS]
    filters = {'sentiment': selected, 'topic': args.get('topic', '')[:100],
               'region': args.get('region', '')[:100], 'source': args.get('source', '')[:100],
               'from': iso_date(args.get('from')), 'to': iso_date(args.get('to')),
               'q': args.get('q', '').strip()[:300],
               'grouped': (args.getlist('grouped') or ['1'])[-1] != '0'}
    saved_view = saved_ids is not None
    reader_path = '/ulozene' if saved_view else '/archiv' if archive else '/'
    def requested_page(key):
        try: return max(1, int(args.get(key, args.get('page', '1'))))
        except (ValueError, TypeError): return 1
    mood_keys = dict(zip(SENTIMENTS, ('page_positive', 'page_neutral', 'page_negative')))
    mood_pages = {mood: requested_page(key) for mood,key in mood_keys.items()}
    conditions, params = [], []
    if saved_view:
        if saved_ids:
            with connect() as c: lookup_ids=resolve_reader_ids(c,saved_ids)
            conditions.append('a.id IN (' + ','.join('?' for _ in lookup_ids) + ')'); params.extend(lookup_ids)
        else: conditions.append('0')
    if not archive: conditions.append("datetime(a.published_at)>=datetime('now','-48 hours') AND datetime(a.published_at)<=datetime('now')")
    if selected:
        conditions.append('a.sentiment IN (' + ','.join('?' for s in selected) + ')'); params.extend(selected)
    else: conditions.append('0')
    for key in ('topic', 'region'):
        if filters[key]: conditions.append('a.' + key + '=?'); params.append(filters[key])
    if filters['source']:
        conditions.append('(a.source_id=? OR EXISTS(SELECT 1 FROM article_aliases al WHERE al.article_id=a.id AND al.source_id=?))')
        params.extend([filters['source']] * 2)
    if filters['from']:
        boundary=datetime.combine(max(date(2,1,1),date.fromisoformat(filters['from'])),time.min,ZoneInfo('Europe/Prague')).astimezone(timezone.utc)
        conditions.append('datetime(a.published_at)>=datetime(?)'); params.append(boundary.isoformat())
    if filters['to'] and date.fromisoformat(filters['to']) < date.max:
        boundary=datetime.combine(date.fromisoformat(filters['to'])+timedelta(days=1),time.min,ZoneInfo('Europe/Prague')).astimezone(timezone.utc)
        conditions.append('datetime(a.published_at)<datetime(?)'); params.append(boundary.isoformat())
    # Quotes prevent FTS operators, syntax errors and untrusted query fragments.
    if filters['q']:
        conditions.append('a.id IN (SELECT id FROM articles_fts WHERE articles_fts MATCH ?)')
        params.append('"' + filters['q'].replace('"', '""') + '"')
    where = ' AND '.join(conditions) or '1'
    with connect() as c:
        count = c.execute('SELECT count(*) FROM clanky a WHERE ' + where, params).fetchone()[0]
        sentiment_counts={r['sentiment']:r['n'] for r in c.execute('SELECT sentiment,count(*) n FROM clanky a WHERE '+where+' GROUP BY sentiment',params)}
        active = [mood for mood in SENTIMENTS if sentiment_counts.get(mood,0)]
        per_group = PAGE_SIZE // max(1,len(active))
        sections = []
        for mood,label,color in zip(SENTIMENTS,('Pozitívne správy','Neutrálne správy','Negatívne správy'),('positive','neutral','negative')):
            n = sentiment_counts.get(mood,0)
            if not n: continue
            rows = c.execute('SELECT '+ARTICLE_COLUMNS+',s.name source_name FROM clanky a LEFT JOIN sources s ON s.id=a.source_id WHERE ' + where + ' AND a.sentiment=? ORDER BY datetime(a.published_at) DESC,a.id DESC', params + [mood]).fetchall()
            items = [article(r) for r in rows]
            cards = group_articles(items, load_aliases(c, (item['id'] for item in items)), enabled=filters['grouped'])
            pages = math.ceil(len(cards)/per_group); page = min(mood_pages[mood],pages)
            mood_pages[mood] = page
            sections.append(dict(sentiment=mood,label=label,color=color,articles=cards[(page-1)*per_group:page*per_group],count=n,card_count=len(cards),page=page,pages=pages))
        latest = c.execute('SELECT max(published_at) FROM clanky').fetchone()[0]
        recent_count = c.execute("SELECT count(*) FROM clanky WHERE datetime(published_at)>=datetime('now','-48 hours') AND datetime(published_at)<=datetime('now')").fetchone()[0]
        sources = [dict(r) for r in c.execute('SELECT id,name FROM sources ORDER BY name')]
        topics = sorted(set(TOPICS) | {r[0] for r in c.execute("SELECT DISTINCT topic FROM clanky WHERE topic IS NOT NULL AND topic<>''")})
        regions = [r[0] for r in c.execute("SELECT DISTINCT region FROM clanky WHERE region IS NOT NULL AND region<>'' ORDER BY region")]
    def page_url(number, mood=None):
        pairs = [(k, v) for k in ('topic','region','source','from','to','q') if (v := filters[k])]
        pairs.extend([('sentiment', s) for s in selected]); pairs.append(('filtered','1'))
        if not filters['grouped']: pairs.append(('grouped','0'))
        for current in active:
            value = number if current == mood else mood_pages[current]
            if value > 1: pairs.append((mood_keys[current],value))
        return reader_path + '?' + urlencode(pairs)
    for section in sections:
        section['previous_url'] = page_url(section['page']-1,section['sentiment']) if section['page']>1 else None
        section['next_url'] = page_url(section['page']+1,section['sentiment']) if section['page']<section['pages'] else None
    return dict(articles=[item for section in sections for item in section['articles']], mood_sections=sections, count=count,
                filters=filters, sources=sources, topics=topics, regions=regions,
                latest=latest, recent_count=recent_count, sentiment_counts=sentiment_counts, archive=archive,
                saved_view=saved_view, saved_ids=saved_ids or [], has_saved_items=bool(saved_ids), reader_path=reader_path,
                page_title='Uložené' if saved_view else 'Archív' if archive else 'Prehľad',
                page_heading='Uložené články' if saved_view else 'Archív správ' if archive else 'Prehľad dňa')
