"""Admission/queue/retention boundaries with no network or live AI."""
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import pytest
import database
import curation
import pipeline
import worker
from test_pipeline import Client,result
from test_web import web,insert_article,access_token
from werkzeug.datastructures import MultiDict
from web_queries import list_articles, highlight_sections

UTC=timezone.utc
PRAGUE=ZoneInfo('Europe/Prague')
NOW=datetime(2026,10,3,23,0,tzinfo=PRAGUE)

@pytest.fixture
def db(tmp_path,monkeypatch):
    monkeypatch.setattr(database,'DB_FILE',str(tmp_path/'curation.db'));database.init_db();return tmp_path


def candidate(ident,pub='news.example',published=None,title=None,category='Slovensko',excerpt=None,state='candidate',available=None):
    source_id='source-'+pub
    payload={'id':ident,'title':title or 'Samostatná udalosť číslo '+ident,'excerpt':excerpt or 'Úplný podklad o samostatnej udalosti '+ident+'. '*10,
        'canonical_url':'https://'+pub+'/'+ident,'link':'https://'+pub+'/'+ident,'source_id':source_id,
        'published_at':(published or NOW-timedelta(hours=1)).astimezone(UTC).isoformat(timespec='seconds'),'language':'sk','category':category}
    with database.connect() as c:
        c.execute('INSERT OR IGNORE INTO sources(id,url,name,category,language) VALUES(?,?,?,?,?)',(source_id,'https://'+pub+'/rss',pub,category,'sk'))
        c.execute('INSERT INTO tasks(id,payload,state,available_at,created_at,updated_at) VALUES(?,?,?,?,?,?)',(ident,json.dumps(payload),state,available or payload['published_at'],database.utcnow(),database.utcnow()))
    return payload


def states():
    with database.connect() as c:return {r['id']:r['state'] for r in c.execute('SELECT id,state FROM tasks')}


def reserve_count(day=None):
    with database.connect() as c:
        return c.execute('SELECT count(*) FROM editorial_reservations'+(' WHERE day=?' if day else ''),(day,) if day else ()).fetchone()[0]


def test_daily_cap_and_publisher_cap_survive_concurrent_selection_and_restart(db):
    for p in range(14):
        for n in range(10):candidate(f'{p}-{n}',pub=f'paper{p}.example')
    with ThreadPoolExecutor(max_workers=2) as pool:chosen=list(pool.map(lambda _:curation.select_candidates(NOW),range(2)))
    assert sum(chosen)==80 and reserve_count()==80
    assert curation.select_candidates(NOW)==0 and reserve_count()==80
    with database.connect() as c:
        assert max(r[0] for r in c.execute('SELECT count(*) FROM editorial_reservations GROUP BY publisher'))<=8
        assert c.execute("SELECT count(*) FROM tasks WHERE state='candidate'").fetchone()[0]==60
        assert c.execute('SELECT count(*) FROM ai_usage').fetchone()[0]==0


def test_subdomains_and_rss_channels_share_publisher_allowance(db):
    assert curation.publisher('spravy.pravda.sk')==curation.publisher('kultura.pravda.sk')=='pravda.sk'
    assert curation.publisher('feeds.bbci.co.uk')==curation.publisher('www.bbc.com')=='bbc.com'
    for n in range(15):candidate(str(n),pub='section'+str(n)+'.teraz.sk')
    assert curation.select_candidates(NOW)==8


def test_cumulative_slots_do_not_burst_day_budget_in_morning(db):
    early=NOW.replace(hour=0)
    for p in range(14):
        for n in range(10):candidate(f'{p}-{n}',pub=f'paper{p}.example',published=early-timedelta(hours=1))
    assert curation.select_candidates(early)==6
    assert curation.select_candidates(early+timedelta(minutes=90))==0
    assert curation.select_candidates(early+timedelta(hours=2))==7
    assert curation.select_candidates(early+timedelta(hours=10))==27
    assert reserve_count()==40


def test_freshness_windows_preserve_archive_and_do_not_infer(db):
    candidate('old-news',published=NOW-timedelta(hours=49))
    candidate('boundary',published=NOW-timedelta(hours=48))
    candidate('evergreen',pub='www.positive.news',published=NOW-timedelta(days=6))
    candidate('expired-green',pub='www.goodgoodgood.co',published=NOW-timedelta(days=7,seconds=1))
    insert_article('archive',published='2020-01-01T00:00:00Z')
    assert curation.select_candidates(NOW)==2
    assert states()=={'old-news':'skipped','boundary':'pending','evergreen':'pending','expired-green':'skipped'}
    with database.connect() as c:assert c.execute('SELECT nadpis FROM clanky WHERE id="archive"').fetchone()


def test_newer_political_news_is_not_displaced_by_preferred_topics(db):
    early=NOW.replace(hour=0)
    for n in range(6):candidate('p'+str(n),pub=f'politics{n}.example',published=early-timedelta(hours=1),title=f'Politik vyhlásil nové vyjadrenie a kritizoval opozíciu {n}')
    for n in range(6):candidate('s'+str(n),pub=f'science{n}.example',published=early-timedelta(hours=24),title=f'Vedci objavili novú účinnú liečbu ochorenia {n}')
    curation.select_candidates(early)
    with database.connect() as c:ids={r[0] for r in c.execute('SELECT task_id FROM editorial_reservations')}
    assert ids=={'p0','p1','p2','p3','p4','p5'}


def test_admission_score_has_no_topic_keyword_or_positive_publisher_bias():
    base={'published_at':(NOW-timedelta(hours=1)).isoformat(),'excerpt':'Rovnako dlhý informačný podklad o aktuálnej udalosti.'}
    variants=[
        {'title':'Politik vyhlásil reakciu a kritizoval opozíciu online','category':'Politika','publisher':'politics.example'},
        {'title':'Nehoda a lúpež, polícia zadržala podozrivého','category':'Slovensko','publisher':'news.example'},
        {'title':'Vedci objavili novú liečbu v nemocnici','category':'Zdravie','publisher':'positive.news'},
        {'title':'Študenti chránia prírodu a klímu','category':'Vzdelávanie','publisher':'school.example'},
    ]
    assert len({curation.score({**base,**variant},NOW) for variant in variants})==1


def test_home_highlight_does_not_hide_newer_politics_behind_science():
    articles=[
        {'id':'politics','topic':'Politika','link':'https://politics.example/a','published_at':'2026-10-05T10:00:00Z'},
        {'id':'science','topic':'Veda a technológie','link':'https://science.example/a','published_at':'2026-10-05T09:00:00Z'},
    ]
    sections=highlight_sections([{'sentiment':'Neutrálny','articles':articles}],limit=1)
    assert sections[0]['articles'][0]['id']=='politics'


def test_about_page_describes_neutral_topic_policy(web):
    client,_=web
    page=client.get('/o-projekte')
    assert page.status_code==200
    assert 'politika má rovnaké podmienky'.encode() in page.data
    assert 'vyššou prioritou vedy'.encode() not in page.data


def test_same_event_guards_and_best_rss_context_selected_once(db):
    title='Vedci objavili nový spôsob recyklácie lítiových batérií'
    excerpt='Vedci v Bratislave predstavili nový spôsob recyklácie batérií. Výsledok zatiaľ čaká na nezávislé potvrdenie.'
    a=candidate('a',pub='first.example',title=title,excerpt=excerpt)
    b=candidate('b',pub='second.example',title=title,excerpt=excerpt+' Výskum trval tri roky.')
    assert curation.same_event(a,b)
    assert not curation.same_event(a,{**b,'title':title+' 20'})
    assert not curation.same_event(a,{**b,'title':'Vedci nie objavili nový spôsob recyklácie lítiových batérií'})
    assert not curation.same_event(a,{**b,'published_at':(NOW-timedelta(days=1)).isoformat()})
    assert curation.select_candidates(NOW)==1
    assert states()=={'a':'duplicate','b':'pending'}
    with database.connect() as c:
        assert c.execute('SELECT count(*) FROM article_aliases').fetchone()[0]==0
        assert c.execute('SELECT representative_id FROM editorial_links').fetchone()[0]=='b'


def test_real_admission_to_pipeline_attaches_sources_without_second_ai_call(db,monkeypatch):
    now=datetime.now(UTC)
    title='Vedci objavili nový spôsob recyklácie lítiových batérií'
    text='Vedci v Bratislave predstavili nový spôsob recyklácie batérií. Výsledok zatiaľ čaká na nezávislé potvrdenie.'
    candidate('a',pub='first.example',title=title,excerpt=text,published=now-timedelta(hours=1))
    candidate('b',pub='second.example',title=title,excerpt=text,published=now-timedelta(hours=1))
    curation.select_candidates(now)
    def extract(item):return {**item,'text':item['excerpt'],'content_hash':hashlib.sha256(item['excerpt'].encode()).hexdigest(),'source_scope':'rss'}
    monkeypatch.setattr(pipeline,'extract_article',extract)
    client=Client();assert pipeline.process_queue(client,max_batches=1)==1
    assert len(client.calls)==1 and len(json.loads(client.calls[0][1]))==1
    with database.connect() as c:
        assert c.execute('SELECT count(*) FROM clanky').fetchone()[0]==1
        assert c.execute('SELECT count(*) FROM article_aliases').fetchone()[0]==1
        assert c.execute("SELECT attempts FROM tasks WHERE state='duplicate'").fetchone()[0]==0


def test_midnight_re_admits_unfinished_places_with_new_allowance_and_retry_backoff(db):
    for p in range(12):candidate(str(p),pub=f'paper{p}.example')
    assert curation.select_candidates(NOW)==12
    morning=NOW.replace(hour=0)+timedelta(days=1)
    assert curation.select_candidates(morning)==6
    assert reserve_count(morning.date().isoformat())==6
    assert sum(v=='pending' for v in states().values())==6
    assert curation.select_candidates(morning)==0


def test_paused_or_quota_blocks_new_admission(db):
    candidate('a');database.set_setting('pipeline_paused','1')
    assert curation.select_candidates(NOW)==0 and reserve_count()==0
    database.set_setting('pipeline_paused','0');database.set_setting('quota_until','2099-01-01T00:00:00Z')
    assert curation.select_candidates(NOW)==0 and reserve_count()==0


def test_candidates_do_not_block_podcast_but_admitted_jobs_do(db):
    day='2026-10-02';candidate('a',published=NOW-timedelta(days=1))
    with database.connect() as c:c.execute('INSERT INTO podcast_days(day,created_at) VALUES(?,?)',(day,database.utcnow()))
    assert day in worker.ready_podcast_days()
    curation.select_candidates(NOW)
    assert day not in worker.ready_podcast_days()


def test_twenty_home_highlights_full_list_and_filter_statistics(web):
    client,_=web
    for mood,prefix in [('Pozitívny','p'),('Neutrálny','n'),('Negatívny','b')]:
        for n in range(15):insert_article(prefix+str(n),title='Samostatná téma '+prefix+str(n),sentiment=mood)
    result=list_articles(MultiDict())
    assert result['featured'] and result['displayed_count']==20 and result['count']==45
    assert len(result['articles'])==20 and all(s['pages']==1 for s in result['mood_sections'])
    page=client.get('/');assert page.data.count(b'class="article-row"')==20 and b'/?view=all' in page.data
    full=client.get('/?view=all');assert full.data.count(b'class="article-row"')==30 and b'view=all' in full.data
    filtered=list_articles(MultiDict({'q':'Samostatná'}));assert not filtered['featured'] and len(filtered['articles'])==30
    assert client.get('/archiv').data.count(b'class="article-row"')==30
    with database.connect() as c:assert c.execute('SELECT count(*) FROM ai_usage').fetchone()[0]==0


def test_admin_shows_selection_policy_and_human_readable_reasons(web,monkeypatch):
    client,_=web;candidate('too-old',published=datetime.now(UTC)-timedelta(days=4));curation.select_candidates()
    _,_,token=access_token(monkeypatch)
    page=client.get('/admin',headers={'Cf-Access-Jwt-Assertion':token})
    assert page.status_code==200 and 'Výber správ'.encode() in page.data
    assert 'Podklad je starší než povolené obdobie'.encode() in page.data


def test_selected_retry_ages_out_without_releasing_its_daily_place(db):
    candidate('a',published=NOW-timedelta(hours=47))
    assert curation.select_candidates(NOW)==1
    later=NOW+timedelta(hours=2)
    # Same-day expiry is checked even for a selected item whose retry is delayed.
    with database.connect() as c:c.execute("UPDATE editorial_reservations SET day=?",(later.date().isoformat(),))
    assert curation.select_candidates(later)==0
    assert states()['a']=='skipped' and reserve_count()==1


def test_malformed_and_future_candidates_never_reach_inference(db):
    candidate('future',published=NOW+timedelta(hours=1),available=(NOW-timedelta(hours=1)).astimezone(UTC).isoformat(timespec='seconds'))
    candidate('bad')
    with database.connect() as c:c.execute("UPDATE tasks SET payload='[]' WHERE id='bad'")
    assert curation.select_candidates(NOW)==0
    assert states()=={'future':'skipped','bad':'skipped'}
    assert reserve_count()==0


def test_duplicate_links_follow_exact_content_alias_to_existing_archive(db):
    title='Vedci objavili nový spôsob recyklácie lítiových batérií'
    text='Vedci v Bratislave predstavili nový spôsob recyklácie batérií. Výsledok zatiaľ čaká na nezávislé potvrdenie.'
    a=candidate('a',title=title,excerpt=text,pub='first.example')
    b=candidate('b',title=title,excerpt=text,pub='second.example')
    curation.select_candidates(NOW)
    insert_article('original')
    with database.connect() as c:
        leader=c.execute('SELECT task_id FROM editorial_reservations').fetchone()[0]
        payload=a if leader=='a' else b
        c.execute('INSERT INTO article_aliases VALUES(?,?,?,?)',('original',payload['source_id'],payload['canonical_url'],payload['title']))
        c.execute("UPDATE tasks SET state='done' WHERE id=?",(leader,))
        curation.publish_aliases(c)
        assert c.execute('SELECT count(*) FROM article_aliases WHERE article_id="original"').fetchone()[0]==2
        assert c.execute('SELECT count(*) FROM clanky').fetchone()[0]==1


def test_failed_representative_releases_other_source_for_new_selection(db):
    title='Vedci objavili nový spôsob recyklácie lítiových batérií'
    text='Vedci v Bratislave predstavili nový spôsob recyklácie batérií. Výsledok zatiaľ čaká na nezávislé potvrdenie.'
    candidate('a',title=title,excerpt=text,pub='first.example')
    candidate('b',title=title,excerpt=text,pub='second.example')
    assert curation.select_candidates(NOW)==1
    with database.connect() as c:c.execute("UPDATE tasks SET state='failed' WHERE state='pending'")
    assert curation.select_candidates(NOW)==1
    assert set(states().values())=={'pending','failed'}
    assert reserve_count()==2
