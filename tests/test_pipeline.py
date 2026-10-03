"""Offline queue, deduplication and archive migration regressions."""
import hashlib
import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
import config
import database
import pipeline
from ai_client import AIError


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_FILE', str(tmp_path / 'test.db'))
    database.init_db()
    return tmp_path


def item(article_id='a', text=None):
    text = text or ('A unique source article about a research result. ' * 10 + article_id)
    return {'id': article_id, 'link': 'https://example.org/' + article_id, 'canonical_url': 'https://example.org/' + article_id,
            'title': 'Original ' + article_id, 'language': 'en', 'source_scope': 'full', 'text': text,
            'source_id': 'source', 'category': 'Svet', 'published_at': '2026-10-02T10:00:00+00:00',
            'content_hash': hashlib.sha256(text.encode()).hexdigest()}


def result(article_id='a'):
    return {'id': article_id, 'nadpis': 'Výskum ' + article_id, 'zhrnutie': 'Vedci oznámili výsledok.',
            'sentiment': 'Pozitívny', 'sentiment_reason': 'Výsledok prináša zlepšenie.', 'topic': 'Veda a technológie',
            'region': 'Svet', 'tags': ['výskum'], 'entities': ['Vedci']}


def enqueue(value, attempts=0, state='pending', lease=None):
    with database.connect() as c:
        c.execute('INSERT INTO tasks(id,payload,state,attempts,available_at,lease_until,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                  (value['id'], json.dumps(value), state, attempts, database.utcnow(), lease, database.utcnow(), database.utcnow()))


def task(article_id):
    with database.connect() as c: return dict(c.execute('SELECT * FROM tasks WHERE id=?', (article_id,)).fetchone())


class Client:
    def __init__(self, behavior=None): self.calls=[]; self.behavior=behavior
    def generate(self, model, instructions, prompt, **kwargs):
        self.calls.append((model, prompt, kwargs))
        if self.behavior: return self.behavior(model, prompt)
        return json.dumps([result(x['id']) for x in json.loads(prompt)])


def test_24_configured_feeds_and_normalization():
    assert len(config.RSS_FEEDS) == 24
    assert config.ALLOWED_MODELS == ('gpt-6-luna', 'gpt-6.1-sol')
    assert pipeline.normalize_url('https://EXAMPLE.org/a?utm_source=x&b=2&a=1#fragment') == 'https://example.org/a?a=1&b=2'
    for url in ('file:///etc/passwd', 'http://user:pass@example.org/a', 'javascript:alert(1)'):
        with pytest.raises(ValueError): pipeline.normalize_url(url)


def test_conditional_fetch_and_same_canonical_url_queue_once(db, monkeypatch):
    url = next(iter(config.RSS_FEEDS))
    monkeypatch.setattr(pipeline, 'RSS_FEEDS', {url: config.RSS_FEEDS[url]})
    monkeypatch.setattr(pipeline.feedparser, 'parse', lambda data: SimpleNamespace(entries=[{'title': 'Article', 'link': 'https://example.org/a?utm_source=first'}, {'title': 'Article', 'link': 'https://example.org/a?utm_source=second'}]))
    class Session:
        calls=[]
        def get(self, url, **kwargs):
            self.calls.append(kwargs['headers'])
            return SimpleNamespace(status_code=200 if len(self.calls)==1 else 304, content=b'feed', headers={'ETag':'etag','Last-Modified':'date'}, raise_for_status=lambda: None)
    session=Session()
    assert pipeline.collect_feeds(session) == 1
    assert pipeline.collect_feeds(session) == 0
    assert session.calls[1]['If-None-Match'] == 'etag'
    assert session.calls[1]['If-Modified-Since'] == 'date'
    with database.connect() as c: assert c.execute('SELECT count(*) FROM tasks').fetchone()[0] == 1


def test_completed_text_duplicate_creates_alias_without_inference(db, monkeypatch):
    first=item(); pipeline.save_result(first,result(),config.ARTICLE_MODEL)
    second=item('b',first['text']); enqueue(second)
    monkeypatch.setattr(pipeline, 'extract_article', lambda value: value)
    client=Client()
    assert pipeline.process_queue(client, max_batches=1) == 1
    assert client.calls == []
    assert task('b')['state'] == 'done'
    with database.connect() as c:
        assert c.execute('SELECT count(*) FROM clanky').fetchone()[0] == 1
        assert dict(c.execute('SELECT * FROM article_aliases').fetchone())['article_id'] == 'a'


def test_same_text_within_claimed_batch_is_analyzed_once(db, monkeypatch):
    first=item(); second=item('b',first['text']); enqueue(first); enqueue(second)
    monkeypatch.setattr(pipeline, 'extract_article', lambda value: value)
    client=Client(); assert pipeline.process_queue(client, max_batches=1) == 2
    inferred=[entry for _,prompt,_ in client.calls for entry in json.loads(prompt)]
    assert len(inferred) == 1
    with database.connect() as c:
        assert c.execute('SELECT count(*) FROM clanky').fetchone()[0] == 1
        assert c.execute('SELECT count(*) FROM article_aliases').fetchone()[0] == 1


def test_batch_entities_remain_grounded_in_each_articles_own_source(db, monkeypatch):
    first=item('a','Christa Pike mala pri čine partnera. Jeho meno tento článok neuvádza. ' * 4)
    second=item('b','Christa Pike committed the crime with her partner Tadaryl Shipp. ' * 4)
    third=item('c','Vo Vrútkach otvorili nový park pre miestnych obyvateľov. ' * 4)
    fourth=item('d','Donald Trump addressed the crowd. ' * 4)
    fifth=item('e','John Smith met Jane Brown. ' * 4)
    for value in (first,second,third,fourth,fifth): enqueue(value)
    monkeypatch.setattr(pipeline,'extract_article',lambda value:value)
    def leaked(model,prompt):
        values=[]
        for value in json.loads(prompt):
            output=result(value['id'])
            output['entities']={'c':['Vrútky'],'d':['Donald Truman'],'e':['John Brown']}.get(value['id'],['Christa Pike','Tadaryl Shipp'])
            values.append(output)
        return json.dumps(values)
    client=Client(leaked)
    assert pipeline.process_queue(client,max_batches=1)==5
    assert len(client.calls)==1
    with database.connect() as c:
        actual={row['id']:json.loads(row['entities']) for row in c.execute('SELECT id,entities FROM clanky')}
    assert actual=={'a':['Christa Pike'],'b':['Christa Pike','Tadaryl Shipp'],'c':['Vrútky'],'d':[],'e':[]}


def test_quota_postponement_does_not_consume_attempts(db, monkeypatch):
    for ident in ('a','b'): enqueue(item(ident), attempts=2)
    monkeypatch.setattr(pipeline, 'extract_article', lambda value: value)
    def quota(model,prompt): raise AIError('rate_limit', transient=True, quota=True)
    assert pipeline.process_queue(Client(quota), max_batches=1) == 0
    for ident in ('a','b'):
        assert task(ident)['state'] == 'pending'
        assert task(ident)['attempts'] == 2
        assert task(ident)['lease_until'] is None
    assert database.setting('quota_until') > database.utcnow()
    untouched=Client(); assert pipeline.process_queue(untouched,max_batches=1)==0; assert untouched.calls==[]


def test_partial_batch_success_survives_later_editor_error(db, monkeypatch):
    for ident in ('a','b'): enqueue(item(ident))
    monkeypatch.setattr(pipeline, 'extract_article', lambda value: value)
    def partial(model,prompt):
        if model==config.ARTICLE_MODEL:return json.dumps([result('a')])
        raise AIError('network_error',transient=True)
    assert pipeline.process_queue(Client(partial),max_batches=1)==1
    assert task('a')['state']=='done'
    assert task('b')['state']=='pending'
    with database.connect() as c:
        c.execute('UPDATE tasks SET available_at=? WHERE id=?',(database.utcnow(),'b'))
    recovered=Client(); assert pipeline.process_queue(recovered,max_batches=1)==1
    assert [x['id'] for _,p,_ in recovered.calls for x in json.loads(p)] == ['b']


def test_concurrent_claimers_never_overlap(db):
    for i in range(10):enqueue(item(str(i)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed=list(pool.map(lambda _:pipeline.claim_tasks(5),range(2)))
    ids=[x['id'] for group in claimed for x in group]
    assert len(ids)==len(set(ids))==10


def test_expired_lease_recovery_stops_after_three_attempts(db):
    expired=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(timespec='seconds')
    enqueue(item('recover'),attempts=1,state='processing',lease=expired)
    enqueue(item('spent'),attempts=3,state='processing',lease=expired)
    assert [t['id'] for t in pipeline.claim_tasks()] == ['recover']
    assert task('recover')['attempts']==2
    assert task('spent')['state']=='failed'


def test_transient_failure_stops_after_third_attempt(db):
    enqueue(item(),attempts=2);pipeline.claim_tasks();pipeline.fail_task('a','network_error',True)
    assert task('a')['state']=='failed'


def test_long_text_selected_locally_and_original_stored(db, monkeypatch):
    source='A'*30000+'TAIL_UNIQUE_SENTINEL'; value=item(text=source);enqueue(value)
    monkeypatch.setattr(pipeline,'extract_article',lambda value:value)
    client=Client(); assert pipeline.process_queue(client,max_batches=1)==1
    assert len(client.calls)==1
    inp=json.loads(client.calls[0][1])[0]
    assert 'TAIL_UNIQUE_SENTINEL' in inp['text'] and inp['selected_excerpt'] is True
    assert len(inp['text'].encode())<=config.ARTICLE_TEXT_BYTES
    with database.connect() as c: assert c.execute('SELECT full_text FROM clanky').fetchone()[0]==source


def test_schema_rejects_wrong_ids_bad_classification_and_overlong_tags():
    for change in ({'id':'wrong'},{'sentiment':'happy'},{'topic':'made up'},{'tags':['t']*6},{'entities':['x']*13},{'zhrnutie':''}):
        with pytest.raises(ValueError): pipeline.validate_result({**result(),**change},'a')


def test_legacy_4217_rows_fts_and_migration_are_idempotent(tmp_path,monkeypatch):
    path=tmp_path/'legacy.db';monkeypatch.setattr(database,'DB_FILE',str(path))
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE clanky(id TEXT PRIMARY KEY,nadpis TEXT NOT NULL,link TEXT NOT NULL,zhrnutie TEXT,sentiment TEXT,kategoria TEXT,datum_publikovania TEXT,povodny_nadpis TEXT,full_text TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        c.executemany('INSERT INTO clanky(id,nadpis,link,zhrnutie,datum_publikovania,full_text) VALUES(?,?,?,?,?,?)',[(str(i),'Historical title '+str(i),'https://example.org/'+str(i),'legacy summary','01.03.2026','Original '+str(i)) for i in range(4217)])
    database.init_db();database.init_db();pipeline.normalize_legacy_urls()
    with database.connect() as c:
        assert c.execute('SELECT count(*) FROM clanky').fetchone()[0]==4217
        assert c.execute('SELECT count(*) FROM articles_fts').fetchone()[0]==4217
        assert c.execute('SELECT count(*) FROM clanky WHERE full_text LIKE "Original %"').fetchone()[0]==4217
        assert c.execute('SELECT published_at FROM clanky LIMIT 1').fetchone()[0]=='2026-02-28T23:00:00+00:00'
        c.execute('UPDATE clanky SET nadpis=? WHERE id=?',('Updated searchable token','0'))
        assert c.execute('SELECT count(*) FROM articles_fts WHERE articles_fts MATCH "searchable"').fetchone()[0]==1
    database.init_db()
    with database.connect() as c: assert c.execute('SELECT count(*) FROM articles_fts').fetchone()[0]==4217


def test_malformed_result_ids_are_ignored_and_valid_siblings_survive():
    client=Client(lambda model,prompt:json.dumps([{'id':[]},result('a'),{'id':{'bad':'id'}},result('b')]))
    assert set(pipeline.analyze([item('a'),item('b')],client))=={'a','b'}


def test_additive_episode_lease_migration_preserves_existing_transcript(tmp_path,monkeypatch):
    path=tmp_path/'existing.db';monkeypatch.setattr(database,'DB_FILE',str(path));database.init_db()
    with database.connect() as c:
        c.execute('ALTER TABLE episodes DROP COLUMN lease_until')
        c.execute("INSERT INTO episodes(id,kind,day,title,transcript,status,created_at) VALUES('old','positive','2026-10-01','Old episode','Original transcript','ready',?)",(database.utcnow(),))
    database.init_db();database.init_db()
    with database.connect() as c:
        assert 'lease_until' in {r['name'] for r in c.execute('PRAGMA table_info(episodes)')}
        assert c.execute('SELECT transcript FROM episodes WHERE id="old"').fetchone()[0]=='Original transcript'


def test_total_feed_outage_is_not_a_successful_collection(db,monkeypatch):
    import requests
    class Offline:
        def get(self,*args,**kwargs):raise requests.ConnectionError('private transport detail')
    with pytest.raises(RuntimeError,match='all_sources_unavailable'):pipeline.collect_feeds(Offline())
    with database.connect() as c:
        assert c.execute('SELECT count(*) FROM sources WHERE error="feed_unavailable"').fetchone()[0]==24
        assert c.execute('SELECT count(*) FROM sources WHERE last_success IS NOT NULL').fetchone()[0]==0


def extraction_session(html):
    class Session:
        def get(self,url,**kwargs):
            return SimpleNamespace(text=html,content=html.encode(),raise_for_status=lambda:None)
    return Session()


@pytest.mark.parametrize('screen',[
    'iDNES a reklama. Váš souhlas umožňuje reklamní partneři; podrobné nastavení. '*8,
    'Before you continue. Choose your consent and advertising preferences. '*8,
    'Your privacy choices. Select partners and approve personalised advertising. '*8,
    'Před pokračováním vyberte: reklamní partneři, podrobné nastavení a váš souhlas. '*8,
])
def test_consent_screen_extraction_uses_rss_article_evidence(monkeypatch,screen):
    excerpt='Vedci predstavili nový výsledok výskumu s konkrétnym prínosom pre miestnych obyvateľov.'
    payload=item();payload['excerpt']=excerpt
    html='<html><body><h1>Consent</h1><p>'+screen+'</p></body></html>'
    extraction=[]
    def extract(source,**kwargs):extraction.append(source);return screen
    monkeypatch.setattr(pipeline.trafilatura,'extract',extract)
    actual=pipeline.extract_article(payload,extraction_session(html))
    assert extraction==[html]
    assert actual['source_scope']=='rss' and actual['text']==excerpt
    assert actual['content_hash']==hashlib.sha256(excerpt.encode()).hexdigest()
    assert 'reklamní partneři' not in actual['text']


def test_regular_privacy_news_article_keeps_full_source(monkeypatch):
    article=('Vedci skúmali súkromie občanov a ochranu osobných údajov. '
             'Správa porovnáva privacy choices používateľov a reklamných partnerov na základe výsledkov výskumu. '*5)
    payload=item();payload['excerpt']='Short RSS summary.'
    html='<article><h1>Výskum o súkromí</h1><p>'+article+'</p></article>'
    monkeypatch.setattr(pipeline.trafilatura,'extract',lambda source,**kwargs:article)
    actual=pipeline.extract_article(payload,extraction_session(html))
    assert actual['source_scope']=='full' and actual['text']==article.strip()


def test_same_article_explicit_reanalysis_does_not_alias_itself(db,monkeypatch):
    original=item();pipeline.save_result(original,result(),config.ARTICLE_MODEL);enqueue(original)
    monkeypatch.setattr(pipeline,'extract_article',lambda value:value)
    client=Client();assert pipeline.process_queue(client,max_batches=1)==1
    assert len(client.calls)==1
    with database.connect() as c:
        assert c.execute('SELECT count(*) FROM article_aliases').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM clanky').fetchone()[0]==1


def test_source_cursor_rotates_sources_and_keeps_newest_per_source(db):
    for sid in ('A','B','C'):
        for i in range(3):
            value=item(sid+str(i));value['source_id']=sid;value['published_at']='2026-10-02T1'+str(i)+':00:00+00:00';enqueue(value)
    first=pipeline.claim_tasks(limit=2);second=pipeline.claim_tasks(limit=2)
    assert [t['id'] for t in first]==['A2','B2']
    assert [t['id'] for t in second]==['C2','A1']
    assert database.setting('source_cursor')=='A'


@pytest.mark.parametrize('bad_payload',['not-json','[]','"scalar"','{"source_id":[]}'])
def test_malformed_queued_payload_does_not_block_valid_work(db,monkeypatch,bad_payload):
    with database.connect() as c:
        c.execute('INSERT INTO tasks(id,payload,created_at,updated_at) VALUES(?,?,?,?)',('bad',bad_payload,database.utcnow(),database.utcnow()))
    enqueue(item('valid'))
    monkeypatch.setattr(pipeline,'extract_article',lambda value:value)
    assert pipeline.process_queue(Client(),max_batches=1)==1
    assert task('valid')['state']=='done'
    assert task('bad')['state']!='processing'


def test_additive_episode_retry_migration_preserves_transcript_and_old_state(tmp_path,monkeypatch):
    path=tmp_path/'existing-retries.db';monkeypatch.setattr(database,'DB_FILE',str(path));database.init_db()
    with database.connect() as c:
        for name in ('attempts','available_at'):c.execute('ALTER TABLE episodes DROP COLUMN '+name)
        c.execute("INSERT INTO episodes(id,kind,day,title,transcript,status,created_at) VALUES('old','positive','2026-10-01','Old episode','Preserved transcript','ready',?)",(database.utcnow(),))
    database.init_db();database.init_db()
    with database.connect() as c:
        row=dict(c.execute('SELECT * FROM episodes WHERE id="old"').fetchone())
        assert row['transcript']=='Preserved transcript' and row['status']=='ready' and row['attempts']==0 and row['available_at'] is None


def test_entity_case_matching_preserves_canonical_identity():
    assert pipeline.grounded_entities(['Roberta Smith'],'Robert Smith signed the paper.')==[]
    assert pipeline.grounded_entities(['Robert Fico'],'Hovorili s Robertom Ficom.')==['Robert Fico']
    assert pipeline.grounded_entities(['Vrútky'],'Koncert vo Vrútkach sa skončil.')==['Vrútky']


def test_sixteen_small_articles_use_one_bounded_call(db,monkeypatch):
    for n in range(16):enqueue(item(str(n)))
    monkeypatch.setattr(pipeline,'extract_article',lambda value:value)
    client=Client();assert pipeline.process_queue(client,max_batches=1)==16
    assert len(client.calls)==1 and len(json.loads(client.calls[0][1]))==16
    assert len(client.calls[0][1].encode())+len(pipeline.INSTRUCTIONS.encode())+2000<=config.ARTICLE_INPUT_BYTES


def test_input_groups_bound_serialized_unicode_and_keep_original():
    values=[item(str(n),('Žltý text „\\"quoted\\"“ s dátumom 2026 a menom Anna. '*100)+str(n)) for n in range(16)]
    groups=list(pipeline.input_groups(values))
    assert sum(len(group) for group in groups)==16
    for group in groups:
        weight=len(json.dumps(pipeline.input_payload([inp for _,inp in group]),ensure_ascii=False,separators=(',',':')).encode())+len(pipeline.INSTRUCTIONS.encode())+2000
        assert weight<=config.ARTICLE_INPUT_BYTES
        for original,inp in group:assert len(inp['text'].encode())<=config.ARTICLE_TEXT_BYTES and original in values


def test_cleaning_removes_only_boilerplate_and_exact_duplicate_paragraphs():
    fact='Anna oznámila investíciu 20 miliónov eur. Výsledky však zatiaľ nie sú potvrdené.'
    source='Read more\n'+fact+'\n'+fact+'\nSubscribe to our newsletter today.\nVýskum súvisiacich článkov pokračuje.'
    clean=pipeline.clean_source(source)
    assert clean.count(fact)==1 and 'Výskum súvisiacich článkov pokračuje.' in clean
    assert 'newsletter' not in clean and 'Read more' not in clean


def test_long_selection_covers_middle_end_and_preserves_qualifiers():
    paragraphs=['Vedci Anna a Peter oznámili výsledok. Zatiaľ však nie je potvrdený.']
    paragraphs += [('Sekcia %d opisuje údaje. Dňa 12. marca merali %d vzoriek, ale výsledok je predbežný. '%(n,n))*10 for n in range(30)]
    paragraphs += ['Na záver: konečný počet je 98765 a pokus ešte neskončil.']
    inp=pipeline.prepare_input(item(text='\n\n'.join(paragraphs)))
    assert inp['selected_excerpt'] and len(inp['text'].encode())<=config.ARTICLE_TEXT_BYTES
    assert '98765' in inp['text'] and 'Zatiaľ však nie je potvrdený' in inp['text']
    assert any('Sekcia '+str(n) in inp['text'] for n in range(12,20))


@pytest.mark.parametrize('luna_repair_valid',[True,False])
def test_only_failed_item_repaired_with_luna_before_sol(db,monkeypatch,luna_repair_valid):
    for ident in ('a','b'):enqueue(item(ident))
    monkeypatch.setattr(pipeline,'extract_article',lambda value:value)
    calls=[]
    def response(model,prompt):
        ids=[v['id'] for v in json.loads(prompt)];calls.append((model,ids))
        if len(calls)==1:return json.dumps([result('a')])
        if model==config.ARTICLE_MODEL and not luna_repair_valid:return 'invalid JSON'
        return json.dumps([result('b')])
    client=Client(response);assert pipeline.process_queue(client,max_batches=1)==2
    assert calls[:2]==[(config.ARTICLE_MODEL,['a','b']),(config.ARTICLE_MODEL,['b'])]
    assert calls[2:]==([] if luna_repair_valid else [(config.EDITOR_MODEL,['b'])])
    assert all(kwargs['task']=='article_repair' for _,_,kwargs in client.calls[1:])
