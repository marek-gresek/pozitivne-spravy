"""Conservative, read-only grouping. No model calls or destructive article merges."""
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import urlsplit

WINDOW_SECONDS = 36 * 3600
STOPWORDS = set('a aj ale ani ako az bol bola boli bude by co do dnes ho ich je jeho jej k ked na nad o od po pod pre pri sa si so su s to tu v vo z za ze zo uz ten tato toto ktory ktora nove novy nova spravy'.split())


def words(text):
    plain = ''.join(c for c in unicodedata.normalize('NFKD', text or '').lower() if not unicodedata.combining(c))
    return {w for w in re.findall(r'[a-z0-9]+', plain) if (len(w) > 2 or w.isdigit()) and w not in STOPWORDS}


def timestamp(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def entity_names(item):
    names = set()
    for entity in item.get('entities') or []:
        name = entity.get('name', entity.get('text', entity.get('label', ''))) if isinstance(entity, dict) else entity
        if isinstance(name, str) and words(name):
            names.add(' '.join(sorted(words(name))))
    return names


def signature(item):
    return (words(item.get('nadpis')), words(item.get('zhrnutie')), entity_names(item), timestamp(item.get('published_at')))


def similar(left, right, a, b):
    title_a, summary_a, entities_a, date_a = a
    title_b, summary_b, entities_b, date_b = b
    if date_a is None or date_b is None or abs(date_a - date_b) > WINDOW_SECONDS:
        return False
    if left.get('sentiment') != right.get('sentiment'):
        return False
    for field in ('topic', 'region'):
        if left.get(field) and right.get(field) and left[field] != right[field]:
            return False
    if min(len(title_a), len(title_b)) < 4:
        return False
    if title_a & {'nie', 'bez'} != title_b & {'nie', 'bez'}:
        return False
    # Conflicting numbers in titles commonly describe separate results/events.
    numbers_a = {w for w in title_a if w.isdigit()}
    numbers_b = {w for w in title_b if w.isdigit()}
    if numbers_a != numbers_b:
        return False
    overlap = len(title_a & title_b)
    if overlap < 4:
        return False
    if title_a == title_b:
        return True
    ratio = overlap / len(title_a | title_b)
    if ratio >= .82 and overlap >= 6:
        return True
    summary_ratio = len(summary_a & summary_b) / max(1, len(summary_a | summary_b))
    return ratio >= .72 and bool(entities_a & entities_b) and summary_ratio >= .5


def source_links(items, aliases):
    links, seen = [], set()
    for item in items:
        candidates = [dict(url=item.get('canonical_url') or item.get('link'), title=item.get('povodny_nadpis') or item.get('nadpis'), source_name=item.get('source_name'))]
        candidates.extend(aliases.get(item['id'], []))
        for candidate in candidates:
            url = candidate.get('url')
            if url and url not in seen:
                seen.add(url)
                candidate = dict(candidate)
                if not candidate.get('source_name'):
                    try: candidate['source_name'] = urlsplit(url).hostname
                    except ValueError: pass
                links.append(candidate)
    return links


def publisher(source):
    if source.get('source_name'):
        return source['source_name']
    try:
        return urlsplit(source['url']).netloc or source['url']
    except ValueError:
        return source['url']


def group_articles(items, aliases=None, enabled=True):
    """Compare only group representatives, avoiding transitive event chains."""
    aliases = aliases or {}
    groups, signatures, index = [], [], defaultdict(list)
    for item in items:
        sig = signature(item)
        match = None
        if enabled and len(sig[0]) >= 4:
            candidates = Counter(i for token in sig[0] for i in index[token])
            for i, overlap in candidates.most_common():
                if overlap < 4:
                    break
                if similar(groups[i][0], item, signatures[i], sig):
                    match = i
                    break
        if match is None:
            match = len(groups)
            groups.append([item])
            signatures.append(sig)
            if enabled:
                for token in sig[0]:
                    index[token].append(match)
        else:
            groups[match].append(item)
    result = []
    for members in groups:
        representative = dict(members[0])
        sources = source_links(members, aliases)
        publishers = {publisher(s) for s in sources}
        representative.update(story_members=members[1:], story_sources=sources,
                              story_article_count=len(members), story_source_count=len(publishers))
        result.append(representative)
    return result


def load_aliases(connection, ids):
    result = defaultdict(list)
    # Bounded queries also work with SQLite installations with a 999-variable limit.
    ids = list(ids)
    for start in range(0, len(ids), 400):
        batch = ids[start:start + 400]
        for row in connection.execute('SELECT al.*,s.name source_name FROM article_aliases al LEFT JOIN sources s ON s.id=al.source_id WHERE al.article_id IN (' + ','.join('?' for _ in batch) + ')', batch):
            result[row['article_id']].append(dict(row))
    return result
