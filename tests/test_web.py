"""Web regressions exercise real SQLite, escaping, retention and signed access."""
import importlib
import json
import uuid
from datetime import datetime,timedelta,timezone
import pytest
import database
import config

@pytest.fixture
def web(tmp_path,monkeypatch):
    monkeypatch.setattr(database,'DB_FILE',str(tmp_path/'news.db'))
    monkeypatch.setattr(config,'AUDIO_DIR',tmp_path/'audio');config.AUDIO_DIR.mkdir()
    monkeypatch.delenv('CF_ACCESS_TEAM',raising=False);monkeypatch.delenv('CF_ACCESS_AUD',raising=False);monkeypatch.delenv('SECRET_KEY',raising=False)
    module=importlib.import_module('app');flask=module.create_app();flask.config['TESTING']=True
    return flask.test_client(),module

def insert_article(article_id,title='Čistá energia',published=None,sentiment='Pozitívny',**values):
    now=datetime.now(timezone.utc).isoformat();published=published or now
    data={'id':article_id,'nadpis':title,'link':'https://example.com/news','zhrnutie':'Nové riešenie prináša čistú energiu.','sentiment':sentiment,'published_at':published,'topic':'Veda a technológie','region':'Slovensko','tags':'["energia"]','source_id':'s1'}
    data.update(values)
    with database.connect() as c:c.execute('INSERT INTO clanky ('+','.join(data)+') VALUES('+','.join('?' for _ in data)+')',list(data.values()))

def insert_episode(kind='positive',days=1,status='ready',title='Dobrý deň',**values):
    eid=str(uuid.uuid4());filename=eid+'.mp3';now=datetime.now(timezone.utc)
    data={'id':eid,'kind':kind,'day':values.pop('day',str(now.date())),'title':title,'status':status,'audio_file':filename,'expires_at':(now+timedelta(days=days)).isoformat(),'published_at':now.isoformat(),'created_at':now.isoformat(),'transcript':'Prepis < bezpečný & presný','chapters':'[]','article_ids':'[]'}
    data.update(values)
    with database.connect() as c:c.execute('INSERT INTO episodes ('+','.join(data)+') VALUES('+','.join('?' for _ in data)+')',list(data.values()))
    (config.AUDIO_DIR/filename).write_bytes(b'ID3'+bytes(range(256))*20)
    return eid

def test_home_48h_and_archived_empty_state(web):
    client,_=web
    insert_article('old',title='Historická správa',published=(datetime.now(timezone.utc)-timedelta(days=5)).isoformat())
    response=client.get('/');assert response.status_code==200
    assert 'Za posledných 48 hodín nepribudli nové správy.'.encode() in response.data
    assert b'Historick' not in response.data
    assert 'Historická správa'.encode() in client.get('/archiv').data
    insert_article('new',title='Dnešná správa')
    assert 'Dnešná správa'.encode() in client.get('/').data

def test_defaults_sentiment_combined_filter_fts_and_alias(web):
    client,_=web
    with database.connect() as c:
        c.executemany('INSERT INTO sources(id,url,name) VALUES(?,?,?)',[('s1','https://example.com/rss','Zdroj jeden'),('s2','https://second.com/rss','Zdroj dva')])
    for n,s in enumerate(config.SENTIMENTS):insert_article(str(n),title='Energia '+str(n),sentiment=s)
    body=client.get('/').data
    for n in range(3):assert ('Energia '+str(n)).encode() in body
    with database.connect() as c:c.execute('INSERT INTO article_aliases(article_id,source_id,url,title) VALUES(?,?,?,?)',('0','s2','https://second.com/alias','Rovnaká udalosť'))
    query={'filtered':'1','sentiment':'Pozitívny','topic':'Veda a technológie','region':'Slovensko','source':'s2','q':'Energia'}
    body=client.get('/archiv',query_string=query).data
    assert b'Energia 0' in body and b'Energia 1' not in body
    assert 'Týmto filtrom nezodpovedá žiadny článok.'.encode() in client.get('/archiv?filtered=1').data
    for q in ['"','OR','*','near(',"' OR 1=1 --"]:assert client.get('/archiv',query_string={'q':q}).status_code==200

def test_pagination_preserves_filters(web):
    client,_=web
    for n in range(35):insert_article(str(n),title='Energia '+str(n))
    response=client.get('/archiv?q=Energia&sentiment=Pozit%C3%ADvny&region=Slovensko');body=response.data.decode()
    assert body.count('class="article-row"')==30 and 'page_positive=2' in body and 'q=Energia' in body and 'region=Slovensko' in body
    assert client.get('/archiv?page=2&q=Energia').data.count(b'class="article-row"')==5
    assert client.get('/archiv?page=oops').status_code==200

def test_local_date_boundaries_winter_and_summer(web):
    client,_=web
    insert_article('winter-in',title='Zimná správa',published='2026-01-01T23:30:00+00:00')
    insert_article('winter-out',title='Pred zimným dňom',published='2026-01-01T22:30:00+00:00')
    body=client.get('/archiv?from=2026-01-02&to=2026-01-02').data
    assert 'Zimná správa'.encode() in body and 'Pred zimným dňom'.encode() not in body
    insert_article('summer-in',title='Letná správa',published='2026-07-01T22:30:00+00:00')
    assert 'Letná správa'.encode() in client.get('/archiv?from=2026-07-02&to=2026-07-02').data
    assert client.get('/archiv?from=nonsense').status_code==200

def test_article_xss_unsafe_url_json_and_aliases(web):
    client,_=web
    insert_article('evil',title='<script>alert(1)</script>',link='javascript:alert(1)',canonical_url='javascript:alert(1)',tags='["<img onerror=alert(1)>"]',entities='not JSON',sentiment_reason='<svg onload=alert(1)>')
    with database.connect() as c:c.execute('INSERT INTO article_aliases(article_id,url,title) VALUES(?,?,?)',('evil','javascript:alert(2)','<iframe>'))
    body=client.get('/clanok/evil').data.decode()
    assert '<script>alert(1)' not in body and '&lt;script&gt;' in body
    assert 'href="javascript:' not in body and '<svg onload' not in body and '<iframe>' not in body
    assert client.get('/clanok/missing').status_code==404

def test_audio_ranges_expiration_files_and_legacy(web):
    client,_=web
    live=insert_episode()
    response=client.get('/audio/'+live,headers={'Range':'bytes=0-9'})
    assert response.status_code==206 and len(response.data)==10 and response.mimetype=='audio/mpeg'
    assert response.headers['Cache-Control']=='private, no-store'
    assert client.get('/static/podcast_pozitivny.mp3').headers['Location']=='/audio/'+live
    with database.connect() as c:c.execute('UPDATE episodes SET expires_at=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),live))
    assert client.get('/audio/'+live).status_code==410
    assert client.get('/static/podcast_pozitivny.mp3').status_code==410
    assert client.get('/static/podcast_vsetky.mp3').status_code==410
    assert client.get('/audio/unknown').status_code==404
    assert b'data-audio=' not in client.get('/podcasty/'+live).data
    missing=insert_episode(kind='all');(config.AUDIO_DIR/(missing+'.mp3')).unlink()
    assert client.get('/audio/'+missing).status_code==410

def test_symlinks_and_traversal_not_served(web,tmp_path):
    client,module=web
    eid=insert_episode();file=config.AUDIO_DIR/(eid+'.mp3');file.unlink()
    target=config.AUDIO_DIR/'other.mp3';target.write_bytes(b'secret')
    file.symlink_to(target)
    assert client.get('/audio/'+eid).status_code==410
    file.unlink();outside=tmp_path/'outside.mp3';outside.write_bytes(b'secret');file.symlink_to(outside)
    assert client.get('/audio/'+eid).status_code==410
    with database.connect() as c:c.execute('UPDATE episodes SET audio_file=? WHERE id=?',('../outside.mp3',eid))
    assert client.get('/audio/'+eid).status_code==410

def test_rss_escape_excludes_expired_and_missing(web):
    import xml.etree.ElementTree as ET
    client,_=web
    eid=insert_episode(title='Dobré <správy> & svet')
    expired=insert_episode(days=-1,day='2026-01-01');missing=insert_episode(day='2026-01-02');(config.AUDIO_DIR/(missing+'.mp3')).unlink()
    response=client.get('/podcast/positive.xml');root=ET.fromstring(response.data)
    items=root.findall('./channel/item');assert len(items)==1 and items[0].findtext('title')=='Dobré <správy> & svet'
    assert items[0].findtext('guid')==eid
    assert client.get('/podcast/invalid.xml').status_code==404
    assert b'&lt;' in response.data and b'&amp;' in response.data

def test_podcast_feed_preserves_https_through_cloudflare_tunnel(web):
    import xml.etree.ElementTree as ET
    client,_=web
    eid=insert_episode()
    response=client.get('/podcast/positive.xml',base_url='http://news.example.com',headers={'X-Forwarded-Proto':'https'})
    root=ET.fromstring(response.data)
    assert root.find('./channel/item/enclosure').attrib['url']=='https://news.example.com/audio/'+eid
    assert root.findtext('./channel/item/link')=='https://news.example.com/podcasty/'+eid

def access_token(monkeypatch):
    import jwt
    import security
    from cryptography.hazmat.primitives.asymmetric import rsa
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    monkeypatch.setenv('CF_ACCESS_TEAM','unit-test');monkeypatch.setenv('CF_ACCESS_AUD','expected-audience');monkeypatch.setenv('SECRET_KEY','stable-test-secret')
    class Client:
        def get_signing_key_from_jwt(self,token):
            return type('Key',(),{'key':key.public_key()})()
    monkeypatch.setattr(security,'key_client',lambda _:Client())
    now=datetime.now(timezone.utc)
    claims={'iss':'https://unit-test.cloudflareaccess.com','aud':['expected-audience'],'sub':'test-user','iat':now,'exp':now+timedelta(hours=1)}
    return key,claims,jwt.encode(claims,key,algorithm='RS256')

def test_admin_fail_closed_plain_email_missing_config_forgery(web,monkeypatch):
    client,_=web
    assert client.get('/admin',headers={'Cf-Access-Authenticated-User-Email':'admin@example.com'}).status_code==503
    key,claims,token=access_token(monkeypatch)
    assert client.get('/admin').status_code==403
    assert client.get('/admin',headers={'Cf-Access-Jwt-Assertion':'garbage'}).status_code==403
    import jwt
    claims['aud']='wrong'
    assert client.get('/admin',headers={'Cf-Access-Jwt-Assertion':jwt.encode(claims,key,algorithm='RS256')}).status_code==403
    claims['aud']='expected-audience';claims['iss']='https://attacker.example.com'
    assert client.get('/admin',headers={'Cf-Access-Jwt-Assertion':jwt.encode(claims,key,algorithm='RS256')}).status_code==403
    claims['iss']='https://unit-test.cloudflareaccess.com';claims['exp']=datetime.now(timezone.utc)-timedelta(seconds=1)
    assert client.get('/admin',headers={'Cf-Access-Jwt-Assertion':jwt.encode(claims,key,algorithm='RS256')}).status_code==403
    assert client.get('/admin',headers={'Cf-Access-Jwt-Assertion':token}).status_code==200

def test_admin_csrf_pause_resume_retry_and_nullable_usage(web,monkeypatch):
    client,_=web
    _,_,token=access_token(monkeypatch);headers={'Cf-Access-Jwt-Assertion':token}
    now=database.utcnow()
    with database.connect() as c:
        c.execute('INSERT INTO tasks(id,payload,state,attempts,created_at,updated_at) VALUES(?,?,?,?,?,?)',('failed-task','{}','failed',3,now,now))
        c.execute('INSERT INTO ai_usage(model,task,status,created_at) VALUES(?,?,?,?)',('gpt-6-luna','article','ok',now))
    response=client.get('/admin',headers=headers);assert response.status_code==200 and response.headers['Cache-Control']=='no-store'
    assert client.post('/admin/action',headers=headers,data={'action':'pause'}).status_code==403
    with client.session_transaction() as session:csrf=session['csrf']
    assert client.post('/admin/action',headers=headers,data={'action':'pause','csrf':csrf}).status_code==303
    assert database.setting('pipeline_paused')=='1'
    assert client.post('/admin/action',headers=headers,data={'action':'resume','csrf':csrf}).status_code==303
    assert database.setting('pipeline_paused')=='0'
    assert client.post('/admin/action',headers=headers,data={'action':'retry','csrf':csrf,'target':'failed-task'}).status_code==303
    with database.connect() as c:row=c.execute('SELECT * FROM tasks WHERE id=?',('failed-task',)).fetchone()
    assert row['state']=='pending' and row['attempts']==0

def test_health_and_public_pages(web):
    client,_=web
    assert client.get('/healthz').json=={'status':'ok'}
    assert client.get('/readyz').status_code==200
    for path in ['/','/archiv','/podcasty','/o-projekte']:
        response=client.get(path);assert response.status_code==200
        assert b'frame-ancestors' in response.headers['Content-Security-Policy'].encode()
        assert b'bootstrap' not in response.data.lower()

def test_audio_rejects_nonready_and_root_symlink(web,tmp_path,monkeypatch):
    client,_=web
    eid=insert_episode(status='failed')
    assert client.get('/audio/'+eid).status_code==410
    with database.connect() as c:c.execute("UPDATE episodes SET status='ready' WHERE id=?",(eid,))
    real_root=config.AUDIO_DIR;linked=tmp_path/'linked-audio';linked.symlink_to(real_root,target_is_directory=True)
    monkeypatch.setattr(config,'AUDIO_DIR',linked)
    assert client.get('/audio/'+eid).status_code==410

def test_admin_wrong_signature_algorithm_and_empty_token(web,monkeypatch):
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    client,_=web
    key,claims,_=access_token(monkeypatch)
    wrong=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    for token in [jwt.encode(claims,wrong,algorithm='RS256'),jwt.encode(claims,'untrusted-hmac-secret-that-is-long-enough',algorithm='HS256')]:
        assert client.get('/admin',headers={'Cf-Access-Jwt-Assertion':token}).status_code==403
    assert client.post('/admin/action',data={'action':'pause','csrf':'forged'},headers={'Cf-Access-Authenticated-User-Email':'owner@example.com'}).status_code==403

def test_extreme_valid_date_and_empty_search_never_error(web):
    client,_=web
    insert_article('normal')
    for query in ['from=0001-01-01&to=9999-12-31','q=%22%22','q=%20%20','page=-1','page=999999']:
        assert client.get('/archiv?'+query).status_code==200

def test_each_sentiment_paginates_independently_even_when_positive_is_older(web):
    from urllib.parse import parse_qs,urlsplit
    from web_queries import list_articles
    from werkzeug.datastructures import MultiDict
    client,_=web
    earlier=(datetime.now(timezone.utc)-timedelta(hours=20)).isoformat()
    for n in range(21):insert_article('p'+str(n),title='Potešenie '+str(n),sentiment='Pozitívny',published=earlier)
    for mood,prefix in [('Neutrálny','n'),('Negatívny','b')]:
        for n in range(35):insert_article(prefix+str(n),title='Energia '+prefix+str(n),sentiment=mood)
    page1=list_articles(MultiDict({'q':''}))
    assert [len(s['articles']) for s in page1['mood_sections']]==[10,10,10]
    first=page1['mood_sections'][0]
    query=parse_qs(urlsplit(first['next_url']).query)
    assert query['page_positive']==['2'] and 'page_neutral' not in query
    page2=list_articles(MultiDict([('page_positive','2')]))
    assert set(a['id'] for a in page2['mood_sections'][0]['articles']).isdisjoint(a['id'] for a in first['articles'])
    assert [a['id'] for a in page2['mood_sections'][1]['articles']]==[a['id'] for a in page1['mood_sections'][1]['articles']]
    assert [a['id'] for a in page2['mood_sections'][2]['articles']]==[a['id'] for a in page1['mood_sections'][2]['articles']]
    body=client.get('/?page_positive=2').data.decode()
    assert body.count('class="article-row"')==30
    assert 'Stránkovanie: Pozitívne správy' in body
    last=list_articles(MultiDict([('page_positive','999999')]))['mood_sections'][0]
    assert last['page']==3 and len(last['articles'])==1 and last['next_url'] is None

def test_chapter_metadata_reads_do_not_generate_audio_and_survive_expiry(web):
    client,_=web
    chapters=[{'title':'Úvod < bezpečný','start':0,'text':'Nezverejňovať celé audio cez metadata'}, {'title':'Veda','start':19.2}]
    eid=insert_episode(chapters=json.dumps(chapters,ensure_ascii=False))
    response=client.get('/podcasty/'+eid+'/kapitoly.json')
    assert response.status_code==200 and response.json=={'available':True,'duration':None,'chapters':[{'title':'Úvod < bezpečný','start':0},{'title':'Veda','start':19.2}]}
    with database.connect() as c:
        assert c.execute('SELECT count(*) FROM ai_usage').fetchone()[0]==0
        c.execute("UPDATE episodes SET status='expired' WHERE id=?",(eid,))
    assert client.get('/podcasty/'+eid+'/kapitoly.json').json['available'] is False
    assert len(client.get('/podcasty/'+eid+'/kapitoly.json').json['chapters'])==2
    assert client.get('/podcasty/missing/kapitoly.json').status_code==404


def test_admin_counts_luna_repairs_in_article_usage(web,monkeypatch):
    client,_=web
    _,_,token=access_token(monkeypatch)
    with database.connect() as c:
        c.execute('INSERT INTO ai_usage(model,task,status,total_tokens,created_at) VALUES(?,?,?,?,?)',('gpt-6-luna','article_repair','success',123456,database.utcnow()))
    from flask import template_rendered
    def capture(sender,template,context: dict,**extra):captured.update(context)
    captured={}
    with template_rendered.connected_to(capture,client.application):
        page=client.get('/admin',headers={'Cf-Access-Jwt-Assertion':token})
    assert captured['usage_totals']['total_tokens']==123456 and captured['usage_totals']['calls']==1
    assert page.status_code==200 and 'Oprava článku'.encode() in page.data
    assert '123'.encode() in page.data and '456'.encode() in page.data
    # The row's label must not incorrectly classify repairs outside article totals.
    assert 'Oprava článku<small>Mimo súhrnu článkov'.encode() not in page.data
