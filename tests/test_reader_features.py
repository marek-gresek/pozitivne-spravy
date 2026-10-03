"""Real SQLite read-side behavior and conservative local event matching."""
import json
from datetime import datetime, timedelta, timezone
import database
from story_groups import group_articles
from test_web import web, insert_article


def story(article_id, title='Vedci objavili nový spôsob recyklácie lítiových batérií', **changes):
    item = dict(id=article_id, nadpis=title, zhrnutie='Vedci z Bratislavy predstavili nový spôsob recyklácie lítiových batérií pre elektromobily.',
                sentiment='Pozitívny', topic='Veda a technológie', region='Slovensko',
                published_at='2026-10-03T10:00:00+00:00', link='https://example.com/' + article_id,
                entities=[{'name': 'Bratislava', 'type': 'place'}])
    item.update(changes)
    return item


def test_same_event_keeps_articles_and_all_sources():
    first, second = story('a'), story('b')
    alias = {'url': 'https://third.com/news', 'title': 'Originálny článok', 'source_name': 'Tretí zdroj'}
    grouped = group_articles([first, second], {'b': [alias]})
    assert len(grouped) == 1
    assert grouped[0]['story_members'] == [second]
    assert grouped[0]['story_article_count'] == 2
    assert grouped[0]['story_source_count'] == 2
    assert {s['url'] for s in grouped[0]['story_sources']} == {first['link'], second['link'], alias['url']}
    assert 'story_members' not in first  # The source records are never rewritten.


def test_legacy_categories_are_not_counted_as_publishers():
    a = story('a', kategoria='Slovensko', link='https://www.example.com/news/a')
    b = story('b', kategoria='Zdravie', link='https://www.example.com/news/b')
    grouped = group_articles([a,b])[0]
    assert grouped['story_article_count'] == 2 and grouped['story_source_count'] == 1
    assert {s['source_name'] for s in grouped['story_sources']} == {'www.example.com'}
    assert len(grouped['story_sources']) == 2


def test_near_titles_need_entities_and_summary_support():
    a = story('a', 'Vedci objavili účinný spôsob recyklácie lítiových batérií elektromobilov')
    b = story('b', 'Vedci predstavili účinný spôsob recyklácie lítiových batérií elektromobilov')
    assert len(group_articles([a, b])) == 1
    # Less headline overlap cannot be rescued by merely mentioning the same city.
    c = story('c', 'Bratislava plánuje nové centrum recyklácie použitých batérií elektromobilov')
    assert len(group_articles([a, c])) == 2


def test_similar_words_do_not_merge_separate_events():
    a = story('a')
    for changes in [dict(sentiment='Negatívny'), dict(topic='Ekonomika'), dict(region='Česko'),
                    dict(published_at='2026-10-05T00:00:01Z'), dict(published_at=None)]:
        assert len(group_articles([a, story('b', **changes)])) == 2
    assert len(group_articles([story('a', 'Čistá energia'), story('b', 'Čistá energia')])) == 2
    assert len(group_articles([story('a', 'Bratislava získala 20 nových elektrických autobusov'),
                               story('b', 'Bratislava získala 30 nových elektrických autobusov')])) == 2
    assert len(group_articles([story('a', 'Bratislava získala 20 nových elektrických autobusov'),
                               story('b', 'Bratislava získala nových elektrických autobusov')])) == 2
    assert len(group_articles([story('a', 'Vedci predstavili účinný spôsob recyklácie lítiových batérií'),
                               story('b', 'Vedci nie predstavili účinný spôsob recyklácie lítiových batérií')])) == 2


def test_related_titles_do_not_form_transitive_groups():
    a = story('a', 'Vedci predstavili výskum recyklácie batérií elektromobilov', entities=[])
    b = story('b', a['nadpis']+' Bratislava', entities=[])
    c = story('c', b['nadpis']+' Nitra', entities=[])
    groups = group_articles([a,b,c])
    assert len(groups) == 2 and groups[0]['story_article_count'] == 2


def add_pair():
    for article_id, source in [('same-a', 's1'), ('same-b', 's2')]:
        insert_article(article_id, title='Vedci objavili nový spôsob recyklácie lítiových batérií', source_id=source,
                       link='https://example.com/' + article_id, entities=json.dumps([{'name': 'Bratislava'}]))


def test_grouped_read_pages_keep_statistics_sources_filters_and_detail(web):
    client, _ = web
    with database.connect() as c:
        c.executemany('INSERT INTO sources(id,url,name) VALUES(?,?,?)', [('s1', 'https://one.com/rss', 'Prvý zdroj'), ('s2', 'https://two.com/rss', 'Druhý zdroj')])
    add_pair()
    with database.connect() as c:
        c.execute('INSERT INTO article_aliases(article_id,url,title) VALUES(?,?,?)', ('same-a', 'https://extra.com/source', 'Ďalší pôvodný článok'))
    body = client.get('/archiv').data.decode()
    assert body.count('class="article-row"') == 1
    assert '2 články' in body and 'https://extra.com/source' in body
    assert 'story-member' in body and '/clanok/same-a' in body and '/clanok/same-b' in body
    assert client.get('/archiv?grouped=0').data.count(b'class="article-row"') == 2
    assert client.get('/archiv?grouped=0&grouped=1').data.count(b'class="article-row"') == 1
    filtered = client.get('/archiv?source=s1').data.decode()
    assert filtered.count('class="article-row"') == 1 and '/clanok/same-b' not in filtered
    detail = client.get('/clanok/same-a').data.decode()
    assert '/clanok/same-b' in detail and 'Druhý zdroj' in detail
    with database.connect() as c:
        assert c.execute('SELECT count(*) FROM clanky').fetchone()[0] == 2
        assert c.execute('SELECT count(*) FROM ai_usage').fetchone()[0] == 0


def test_grouping_before_pagination_and_optout_url(web):
    client, _ = web
    add_pair()
    for n in range(29):
        insert_article('unique-' + str(n), title='Samostatná správa číslo ' + str(n))
    first = client.get('/archiv').data
    assert first.count(b'class="article-row"') == 30
    assert b'page_positive=2' not in first
    plain = client.get('/archiv?grouped=0').data
    assert plain.count(b'class="article-row"') == 30 and b'grouped=0' in plain and b'page_positive=2' in plain
    assert client.get('/archiv?grouped=0&page_positive=2').data.count(b'class="article-row"') == 1


def test_saved_ids_are_browser_supplied_filtered_and_never_publicly_cached(web):
    client, _ = web
    insert_article('old-saved', title='Historický uložený článok', published=(datetime.now(timezone.utc) - timedelta(days=100)).isoformat())
    insert_article('not-saved', title='Článok mimo uložených')
    empty = client.get('/ulozene')
    assert empty.status_code == 200 and 'Zatiaľ nemáte uložené články'.encode() in empty.data
    headers = {'X-Saved-Articles': 'old-saved,missing,old-saved'}
    response = client.get('/ulozene', headers=headers)
    assert response.status_code == 200 and 'Historický uložený článok'.encode() in response.data
    assert 'Článok mimo uložených'.encode() not in response.data
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert 'X-Saved-Articles' in response.headers['Vary']
    assert 'Historický uložený článok'.encode() not in client.get('/ulozene?q=nezodpoveda', headers=headers).data
    assert 'Historický uložený článok'.encode() not in client.get('/ulozene?ids=old-saved').data
    assert 'Zatiaľ nemáte uložené články'.encode() in client.get('/ulozene').data
    with database.connect() as c:
        assert c.execute('SELECT count(*) FROM ai_usage').fetchone()[0] == 0


def test_saved_header_validation_and_pagination(web):
    client, _ = web
    for value in ["x' OR 1=1", 'a,,b', 'a' * 81, ','.join('x' + str(n) for n in range(301)), 'a' * 24501]:
        assert client.get('/ulozene', headers={'X-Saved-Articles': value}).status_code == 400
    for n in range(35): insert_article(str(n), title='Uložená energia ' + str(n))
    response = client.get('/ulozene?grouped=0', headers={'X-Saved-Articles': ','.join(str(n) for n in range(35))})
    assert b'/ulozene?' in response.data and b'page_positive=2' in response.data
    assert response.data.count(b'class="article-row"') == 30
    ids = ['x' + str(n).zfill(79) for n in range(300)]
    chunks = [','.join(ids[n:n+74]) for n in range(0,300,74)]
    headers = {'X-Saved-Articles'+('-'+str(i+1) if i else ''):chunk for i,chunk in enumerate(chunks)}
    response = client.get('/ulozene',headers=headers)
    assert response.status_code == 200
    assert 'X-Saved-Articles-5' in response.headers['Vary']


def test_new_article_detection_uses_arrival_time_not_publication(web):
    client, _ = web
    insert_article('arrived-late', published='2020-01-01T00:00:00Z', created_at='2026-10-03 12:00:00')
    for path in ['/archiv', '/clanok/arrived-late']:
        body = client.get(path).data
        assert b'data-first-seen="2026-10-03 12:00:00"' in body
        assert b'data-new-badge' in body and b'data-save-id="arrived-late"' in body
