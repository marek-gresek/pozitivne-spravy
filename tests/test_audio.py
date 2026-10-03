"""Audio retention is independent of inference, filesystem failures and HTTP reads."""
import importlib
import json
import os
import uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
import config
import database
import podcasts

UTC=timezone.utc


@pytest.fixture
def audio_db(tmp_path,monkeypatch):
    monkeypatch.setattr(database,'DB_FILE',str(tmp_path/'test.db'))
    root=tmp_path/'audio';root.mkdir();tmp=root/'tmp';tmp.mkdir()
    for module in (config,podcasts):
        monkeypatch.setattr(module,'AUDIO_DIR',root)
        monkeypatch.setattr(module,'TEMP_AUDIO_DIR',tmp)
    database.init_db()
    return root,tmp


def add_episode(root,status='ready',expires=None,eid=None,**fields):
    eid=eid or str(uuid.uuid4());filename=eid+'.mp3'
    row={'id':eid,'kind':'positive','day':str(uuid.uuid4()),'title':'Episode','transcript':'Preserved original transcript',
         'chapters':json.dumps([{'title':'Chapter','text':'Original','start':0,'article_ids':[]}]),
         'article_ids':'["article"]','status':status,'audio_file':filename,'published_at':datetime.now(UTC).isoformat(timespec='seconds'),
         'expires_at':(expires or (datetime.now(UTC)+timedelta(days=1))).isoformat(timespec='seconds'),'created_at':database.utcnow(),**fields}
    with database.connect() as c:
        c.execute('INSERT INTO episodes('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',list(row.values()))
    (root/filename).write_bytes(b'offline audio')
    return eid,filename


def episode(eid):
    with database.connect() as c:return dict(c.execute('SELECT * FROM episodes WHERE id=?',(eid,)).fetchone())


def test_retention_boundary_idempotence_and_preserved_text(audio_db):
    root,tmp=audio_db;now=datetime.now(UTC).replace(microsecond=0)
    eid,filename=add_episode(root,expires=now)
    keep,keepname=add_episode(root,expires=now+timedelta(seconds=1))
    original=episode(eid)
    assert podcasts.cleanup_audio(now)==len(b'offline audio')
    assert not (root/filename).exists() and (root/keepname).exists()
    row=episode(eid)
    assert row['status']=='expired' and row['deleted_at']==now.isoformat(timespec='seconds')
    for field in ('transcript','chapters','article_ids'):assert row[field]==original[field]
    assert podcasts.cleanup_audio(now)==0
    assert episode(eid)['removed_bytes']==len(b'offline audio')


def test_cleanup_retries_failure_without_losing_text(audio_db,monkeypatch):
    root,tmp=audio_db;now=datetime.now(UTC);eid,filename=add_episode(root,expires=now-timedelta(seconds=1))
    unlink=podcasts.safe_unlink
    def denied(*args):raise PermissionError('filesystem blocked')
    monkeypatch.setattr(podcasts,'safe_unlink',denied)
    assert podcasts.cleanup_audio(now)==0
    assert episode(eid)['deleted_at'] is None and episode(eid)['error']=='cleanup_failed'
    assert (root/filename).exists()
    monkeypatch.setattr(podcasts,'safe_unlink',unlink)
    assert podcasts.cleanup_audio(now)==len(b'offline audio')
    assert episode(eid)['error'] is None and episode(eid)['transcript']=='Preserved original transcript'


@pytest.mark.parametrize('name',['../external.mp3','/etc/passwd','random.mp3','00000000-0000-0000-0000-000000000000.mp3/child'])
def test_unlink_rejects_non_owned_names(audio_db,name):
    root,tmp=audio_db
    with pytest.raises(ValueError):podcasts.safe_unlink(root,name)


def test_unlink_rejects_symlink_file_and_symlink_root(audio_db,tmp_path):
    root,tmp=audio_db;outside=tmp_path/'external.mp3';outside.write_bytes(b'external')
    filename=str(uuid.uuid4())+'.mp3';(root/filename).symlink_to(outside)
    with pytest.raises(ValueError):podcasts.safe_unlink(root,filename)
    alias=tmp_path/'alias';alias.symlink_to(root,target_is_directory=True)
    with pytest.raises(OSError):podcasts.safe_unlink(alias,filename)
    assert outside.read_bytes()==b'external'


def test_cleanup_leaves_symlink_and_unowned_file_untouched(audio_db,tmp_path):
    root,tmp=audio_db;now=datetime.now(UTC);eid,filename=add_episode(root,expires=now-timedelta(days=1))
    (root/filename).unlink();outside=tmp_path/'outside';outside.write_bytes(b'keep');(root/filename).symlink_to(outside)
    (root/'foreign.mp3').write_bytes(b'keep too')
    assert podcasts.cleanup_audio(now)==0
    assert outside.read_bytes()==b'keep' and (root/'foreign.mp3').exists()
    assert episode(eid)['error']=='cleanup_failed' and episode(eid)['deleted_at'] is None


def test_temporary_cleanup_protects_active_lease_and_recent_drafts(audio_db):
    root,tmp=audio_db;now=datetime.now(UTC);active,_=add_episode(root,status='generating',lease_until=(now+timedelta(minutes=20)).isoformat(timespec='seconds'))
    abandoned=str(uuid.uuid4());recent=str(uuid.uuid4())
    active_file=tmp/(active+'-0-0.wav');old_file=tmp/(abandoned+'-0-0.wav');recent_file=tmp/(recent+'.txt')
    for p in (active_file,old_file,recent_file):p.write_bytes(b'draft')
    for p in (active_file,old_file):os.utime(p,(now.timestamp()-90000,now.timestamp()-90000))
    (tmp/'foreign.txt').write_text('unowned')
    assert podcasts.cleanup_audio(now)==len(b'draft')
    assert active_file.exists() and recent_file.exists() and not old_file.exists() and (tmp/'foreign.txt').exists()


def test_expired_audio_in_http_and_rss_before_cleanup(audio_db):
    root,tmp=audio_db;eid,filename=add_episode(root,expires=datetime.now(UTC)-timedelta(seconds=1))
    module=importlib.import_module('app');client=module.create_app().test_client()
    assert client.get('/audio/'+eid).status_code==410
    assert filename.encode() not in client.get('/podcast/positive.xml').data
    assert client.get('/podcasty/'+eid).status_code==200
    assert b'Preserved original transcript' in client.get('/podcasty/'+eid).data
    assert (root/filename).exists()


def test_audio_http_range_and_symlink_rejection(audio_db):
    root,tmp=audio_db;eid,filename=add_episode(root)
    module=importlib.import_module('app');client=module.create_app().test_client()
    r=client.get('/audio/'+eid,headers={'Range':'bytes=0-3'})
    assert r.status_code==206 and r.data==b'offl'
    assert r.headers['Cache-Control']=='private, no-store'
    target=root/(str(uuid.uuid4())+'.mp3');target.write_bytes(b'other episode')
    (root/filename).unlink();(root/filename).symlink_to(target)
    assert client.get('/audio/'+eid).status_code==410


def test_episode_claims_are_exclusive_and_recover_expired_lease(audio_db):
    root,tmp=audio_db;eid,_=add_episode(root,status='pending')
    assert podcasts.claim_episode()['id']==eid
    assert podcasts.claim_episode() is None
    with database.connect() as c:c.execute('UPDATE episodes SET lease_until=? WHERE id=?',((datetime.now(UTC)-timedelta(hours=1)).isoformat(timespec='seconds'),eid))
    assert podcasts.claim_episode()['id']==eid


def test_episode_claim_only_uses_days_with_completed_article_backlog(audio_db):
    root,_=audio_db
    blocked,_=add_episode(root,status='pending',day='2026-10-01')
    eligible,_=add_episode(root,status='pending',day='2026-10-02')
    assert podcasts.claim_episode(allowed_days=set()) is None
    assert podcasts.claim_episode(allowed_days={'2026-10-02'})['id']==eligible
    assert episode(blocked)['status']=='pending' and episode(blocked)['attempts']==0
    assert podcasts.claim_episode(allowed_days={'2026-10-02'}) is None
    # The manual command remains able to bootstrap a specified day.
    assert podcasts.claim_episode()['id']==blocked


def test_script_must_map_selected_articles():
    articles=[{'id':'selected'}]
    with pytest.raises(ValueError):podcasts.validate_script({'chapters':[{'title':'Intro','text':'A vague introduction.','article_ids':[]}]},articles)


def test_daily_selection_has_15_topics_and_positive_filter(audio_db):
    root,tmp=audio_db
    with database.connect() as c:
        for i in range(20):
            c.execute('INSERT INTO clanky(id,nadpis,link,zhrnutie,sentiment,published_at,topic) VALUES(?,?,?,?,?,?,?)',
                (str(i),'Distinct'+str(i),'https://example.org/'+str(i),'Verified summary','Pozitívny' if i%2 else 'Neutrálny','2026-10-02T10:00:00+00:00','Topic'+str(i)))
    assert len(podcasts.select_articles('2026-10-02','all'))==15
    assert len(podcasts.select_articles('2026-10-02','positive'))==10
    assert all(x['sentiment']=='Pozitívny' for x in podcasts.select_articles('2026-10-02','positive'))
    podcasts.ensure_episodes('2026-10-02');podcasts.ensure_episodes('2026-10-02')
    with database.connect() as c:assert c.execute('SELECT count(*) FROM episodes').fetchone()[0]==2


def wav_bytes():
    import io
    import wave
    out=io.BytesIO()
    with wave.open(out,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(22050);w.writeframes(b'\0\0'*5512)
    return out.getvalue()


def speech_setup(monkeypatch,chapters=None):
    article={'id':'article','nadpis':'Article title','zhrnutie':'Verified fact.','topic':'Veda a technológie','kategoria':'Veda'}
    monkeypatch.setattr(podcasts,'select_articles',lambda day,kind:[article])
    calls=[]
    class Reply:
        content=wav_bytes()
        def raise_for_status(self):pass
    def post(url,**kwargs):calls.append((url,kwargs));return Reply()
    monkeypatch.setattr(podcasts.requests,'post',post)
    class Client:
        def generate(self,model,instructions,prompt,**kwargs):
            assert model=='gpt-6.1-sol' and kwargs['task']=='podcast'
            return json.dumps({'chapters':chapters or [{'title':'Prvá správa','text':'Vedci oznámili výsledok.','article_ids':['article']},{'title':'Záver','text':'Ďakujeme za počúvanie.','article_ids':[]}]})
    return Client(),calls


def test_real_mp3_encoder_mono_64k_chapters_and_fourteen_days(audio_db,monkeypatch):
    import shutil
    import subprocess
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):pytest.skip('ffmpeg and ffprobe required')
    root,tmp=audio_db;eid,filename=add_episode(root,status='pending',transcript=None,chapters='[]')
    client,calls=speech_setup(monkeypatch)
    assert podcasts.generate_episode(episode(eid),client)
    row=episode(eid);assert row['status']=='ready' and row['duration']>0
    assert datetime.fromisoformat(row['expires_at'])-datetime.fromisoformat(row['published_at'])==timedelta(days=14)
    probe=subprocess.run(['ffprobe','-v','error','-show_streams','-of','json',str(root/filename)],capture_output=True,text=True,check=True)
    stream=json.loads(probe.stdout)['streams'][0]
    assert stream['codec_name']=='mp3' and stream['channels']==1 and int(stream['bit_rate'])==64000
    timeline=json.loads(row['chapters']);assert timeline[0]['start']==0 and timeline[1]['start']>0
    assert timeline[0]['article_ids']==['article'] and 'text' in timeline[0]
    assert all(c[1]['json']['voice']=='sk_SK-lili-medium' for c in calls)
    assert not list(tmp.iterdir())


def test_same_episode_concurrent_attempts_have_distinct_temporary_paths(audio_db,monkeypatch):
    import shutil
    import threading
    from concurrent.futures import ThreadPoolExecutor
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):pytest.skip('ffmpeg and ffprobe required')
    root,tmp=audio_db;eid,filename=add_episode(root,status='generating',transcript='Saved',chapters=json.dumps([{'title':'Chapter','text':'Saved script.','article_ids':['article']}]))
    client,calls=speech_setup(monkeypatch)
    actual_run=podcasts.subprocess.run;paths=[];lock=threading.Lock();barrier=threading.Barrier(2)
    def run(args,**kwargs):
        if args[0]=='ffmpeg':
            with lock:paths.append(args[-1])
            if '-f' not in args:barrier.wait(timeout=10)
        return actual_run(args,**kwargs)
    monkeypatch.setattr(podcasts.subprocess,'run',run)
    snapshot=episode(eid)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:podcasts.generate_episode(snapshot,client),range(2)))
    assert results==[True,True] and len(paths)==len(set(paths))==4
    assert not list(tmp.iterdir())


def test_long_sentence_speech_requests_are_bounded(audio_db,monkeypatch):
    root,tmp=audio_db;eid,filename=add_episode(root,status='pending',transcript=None,chapters='[]')
    client,calls=speech_setup(monkeypatch,chapters=[{'title':'Long sentence','text':'A'*5000+'.','article_ids':['article']}])
    assert podcasts.generate_episode(episode(eid),client)
    assert max(len(kwargs['json']['text']) for _,kwargs in calls)<=1800


def test_abandoned_attempt_uuid_temp_files_are_cleaned(audio_db):
    root,tmp=audio_db;now=datetime.now(UTC);eid=str(uuid.uuid4());attempt=str(uuid.uuid4())
    files=[tmp/(eid+'-'+attempt+'-0-0.wav'),tmp/(eid+'-'+attempt+'.txt'),tmp/(eid+'-'+attempt+'.mp3')]
    for p in files:p.write_bytes(b'temp');os.utime(p,(now.timestamp()-90000,now.timestamp()-90000))
    assert podcasts.cleanup_audio(now)==12
    assert not any(p.exists() for p in files)


def test_saved_transcript_reused_after_speech_failure(audio_db,monkeypatch):
    import requests
    root,tmp=audio_db;eid,filename=add_episode(root,status='pending',transcript=None,chapters='[]')
    client,calls=speech_setup(monkeypatch)
    original_generate=client.generate;inferences=[]
    def generate(*args,**kwargs):inferences.append(args[0]);return original_generate(*args,**kwargs)
    client.generate=generate
    good_post=podcasts.requests.post
    def fail(*args,**kwargs):raise requests.ConnectionError('offline')
    monkeypatch.setattr(podcasts.requests,'post',fail)
    assert podcasts.generate_episode(episode(eid),client) is False
    stored=episode(eid);assert stored['transcript'] and stored['status']=='failed'
    monkeypatch.setattr(podcasts.requests,'post',good_post)
    assert podcasts.generate_episode(stored,client) is True
    assert len(inferences)==1
    assert episode(eid)['transcript']==stored['transcript']


@pytest.fixture
def private_speech_server(monkeypatch):
    """Load the actual HTTP routes using an offline fixed-voice implementation."""
    import importlib.util
    import sys
    import types
    options=[];spoken=[]
    onnx=types.ModuleType('onnxruntime')
    class Options:pass
    def inference(path,**kwargs):options.append((path,kwargs));return object()
    onnx.SessionOptions=Options;onnx.InferenceSession=inference
    piper=types.ModuleType('piper');configuration=types.ModuleType('piper.config')
    class Voice:
        def __init__(self,**kwargs):pass
        def synthesize_wav(self,text,wav):
            spoken.append(text);wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(22050);wav.writeframes(b'\0\0'*100)
    piper.PiperVoice=Voice
    configuration.PiperConfig=types.SimpleNamespace(from_dict=lambda value:value)
    for name,module in [('onnxruntime',onnx),('piper',piper),('piper.config',configuration)]:monkeypatch.setitem(sys.modules,name,module)
    original_read=Path.read_text
    def read(path,*args,**kwargs):
        return '{}' if str(path)=='/voices/sk_SK-lili-medium.onnx.json' else original_read(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',read)
    source=Path(__file__).resolve().parent.parent/'piper_server.py'
    spec=importlib.util.spec_from_file_location('offline_piper_server',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.app.test_client(),options,spoken


def test_private_fixed_voice_server_returns_actual_wav_and_bounded_cpu_contract(private_speech_server):
    import io
    import wave
    client,options,spoken=private_speech_server
    response=client.post('/synthesize',json={'text':'  Dobrá správa.  ','voice':'sk_SK-lili-medium'})
    assert response.status_code==200 and response.mimetype=='audio/wav' and response.data[:4]==b'RIFF'
    assert spoken==['Dobrá správa.']
    with wave.open(io.BytesIO(response.data),'rb') as wav:assert wav.getnchannels()==1 and wav.getnframes()==100
    assert len(options)==1
    settings=options[0][1]['sess_options']
    assert settings.intra_op_num_threads==settings.inter_op_num_threads==1
    assert options[0][1]['providers']==['CPUExecutionProvider']
    assert client.get('/healthz').json['voice']=='sk_SK-lili-medium'


@pytest.mark.parametrize('payload',[['bad-root'],'bad-root',123,{'text':'x'*1801},{'text':'   '},{'text':'Allowed text','voice':'other-voice'}])
def test_private_speech_rejects_invalid_input_without_synthesis(private_speech_server,payload):
    client,options,spoken=private_speech_server
    assert client.post('/synthesize',json=payload).status_code==400
    assert spoken==[]


def test_private_speech_rejects_oversized_http_body(private_speech_server):
    client,options,spoken=private_speech_server
    assert client.post('/synthesize',json={'text':'x'*16001}).status_code==413
    assert spoken==[]


def make_available(eid):
    with database.connect() as c:c.execute('UPDATE episodes SET available_at=? WHERE id=?',(database.utcnow(),eid))


@pytest.mark.parametrize('failure_kind',['ai','http','filesystem','encoder'])
def test_episode_transient_failures_have_two_retries_and_three_total_attempts(audio_db,monkeypatch,failure_kind):
    import requests
    import subprocess
    from ai_client import AIError
    root,tmp=audio_db;eid,filename=add_episode(root,status='pending',transcript=None,chapters='[]')
    client,calls=speech_setup(monkeypatch)
    if failure_kind=='ai':
        def failed(*args,**kwargs):raise AIError('network_error',transient=True)
        client.generate=failed
    elif failure_kind=='http':
        def failed(*args,**kwargs):raise requests.ConnectionError('private offline detail')
        monkeypatch.setattr(podcasts.requests,'post',failed)
    elif failure_kind=='filesystem':
        def failed(*args,**kwargs):raise OSError('temporary storage error')
        monkeypatch.setattr(Path,'write_bytes',failed)
    else:
        def failed(args,**kwargs):raise subprocess.CalledProcessError(1,args,stderr=b'private encoder detail')
        monkeypatch.setattr(podcasts.subprocess,'run',failed)
    for attempt in (1,2,3):
        claimed=podcasts.claim_episode();assert claimed['id']==eid
        assert episode(eid)['attempts']==attempt
        assert podcasts.generate_episode(claimed,client) is False
        row=episode(eid)
        assert row['status']==('pending' if attempt<3 else 'failed')
        assert row['lease_until'] is None and row['available_at']>database.utcnow()
        assert 'private' not in row['error']
        assert podcasts.claim_episode() is None
        make_available(eid)
    assert podcasts.claim_episode() is None


@pytest.mark.parametrize('prior_attempts',[0,2])
def test_episode_quota_postponement_restores_attempt_and_preserves_script(audio_db,monkeypatch,prior_attempts):
    from ai_client import AIError
    root,tmp=audio_db;eid,filename=add_episode(root,status='pending',transcript=None,chapters='[]',attempts=prior_attempts)
    client,calls=speech_setup(monkeypatch)
    def quota(*args,**kwargs):raise AIError('rate_limit',transient=True,quota=True)
    client.generate=quota
    claimed=podcasts.claim_episode();assert podcasts.generate_episode(claimed,client) is False
    row=episode(eid)
    assert row['status']=='pending' and row['attempts']==prior_attempts and row['lease_until'] is None
    assert row['available_at']>database.utcnow() and database.setting('quota_until')>database.utcnow()
    assert podcasts.process_episodes(client)==0
    assert podcasts.claim_episode() is None


def test_claimed_speech_retry_reuses_saved_script_without_further_inference(audio_db,monkeypatch):
    import requests
    root,tmp=audio_db;eid,filename=add_episode(root,status='pending',transcript=None,chapters='[]')
    client,calls=speech_setup(monkeypatch);inferences=[];generate=client.generate;good_post=podcasts.requests.post
    def count(*args,**kwargs):inferences.append(args[0]);return generate(*args,**kwargs)
    client.generate=count
    def offline(*args,**kwargs):raise requests.ConnectionError('offline')
    monkeypatch.setattr(podcasts.requests,'post',offline)
    assert podcasts.generate_episode(podcasts.claim_episode(),client) is False
    saved=episode(eid);assert saved['status']=='pending' and saved['attempts']==1 and saved['transcript']
    assert podcasts.claim_episode() is None
    make_available(eid);monkeypatch.setattr(podcasts.requests,'post',good_post)
    assert podcasts.generate_episode(podcasts.claim_episode(),client) is True
    row=episode(eid)
    assert row['status']=='ready' and row['attempts']==2 and row['transcript']==saved['transcript']
    assert len(inferences)==1


def test_expired_episode_lease_recovers_and_caps_crashed_attempts(audio_db):
    root,tmp=audio_db;past=(datetime.now(UTC)-timedelta(hours=1)).isoformat(timespec='seconds')
    spent,_=add_episode(root,status='generating',attempts=3,lease_until=past)
    retry,_=add_episode(root,status='generating',attempts=1,lease_until=past)
    assert podcasts.claim_episode()['id']==retry
    assert episode(retry)['attempts']==2
    assert episode(spent)['status']=='failed' and episode(spent)['lease_until'] is None
    assert podcasts.claim_episode() is None


def test_episode_nontransient_ai_failure_fails_immediately(audio_db,monkeypatch):
    from ai_client import AIError
    root,tmp=audio_db;eid,filename=add_episode(root,status='pending',transcript=None,chapters='[]')
    client,calls=speech_setup(monkeypatch)
    def auth(*args,**kwargs):raise AIError('http_401')
    client.generate=auth
    assert podcasts.generate_episode(podcasts.claim_episode(),client) is False
    assert episode(eid)['status']=='failed' and episode(eid)['attempts']==1


def test_episode_directory_failure_is_a_bounded_retry(audio_db,monkeypatch):
    root,tmp=audio_db;eid,filename=add_episode(root,status='pending',transcript=None,chapters='[]')
    client,calls=speech_setup(monkeypatch)
    def unavailable(*args,**kwargs):raise OSError('temporary mount failure')
    monkeypatch.setattr(Path,'mkdir',unavailable)
    assert podcasts.generate_episode(podcasts.claim_episode(),client) is False
    assert episode(eid)['status']=='pending' and episode(eid)['attempts']==1
    assert episode(eid)['lease_until'] is None and episode(eid)['available_at']>database.utcnow()


def test_successful_episode_survives_temporary_cleanup_failure_and_hourly_retry(audio_db,monkeypatch):
    root,tmp=audio_db;eid,filename=add_episode(root,status='pending',transcript=None,chapters='[]')
    client,calls=speech_setup(monkeypatch);original_unlink=Path.unlink
    def denied(path,*args,**kwargs):
        if path.parent==tmp:raise PermissionError('temporary cleanup blocked')
        return original_unlink(path,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',denied)
    assert podcasts.generate_episode(podcasts.claim_episode(),client) is True
    assert episode(eid)['status']=='ready' and (root/filename).exists()
    assert database.setting('temporary_audio_cleanup_error')=='cleanup_pending'
    remaining=list(tmp.iterdir());assert remaining
    monkeypatch.setattr(Path,'unlink',original_unlink)
    now=datetime.now(UTC)
    for path in remaining:os.utime(path,(now.timestamp()-90000,now.timestamp()-90000))
    assert podcasts.cleanup_audio(now)>0
    assert not list(tmp.iterdir()) and (root/filename).exists()


def test_admin_episode_retry_resets_exhausted_counter_and_retains_transcript(audio_db,monkeypatch):
    import security
    root,tmp=audio_db;eid,filename=add_episode(root,status='failed',attempts=3,error='generation_failed',available_at=(datetime.now(UTC)+timedelta(hours=1)).isoformat(),lease_until=(datetime.now(UTC)+timedelta(minutes=1)).isoformat())
    ready,readyfile=add_episode(root,status='ready',attempts=2)
    monkeypatch.setattr(security,'verified_access_claims',lambda token:{'sub':'test-operator'})
    module=importlib.import_module('app');client=module.create_app().test_client()
    assert client.get('/admin').status_code==200
    with client.session_transaction() as session:csrf=session['csrf']
    assert client.post('/admin/action',data={'action':'retry','target_type':'episode','target':eid,'csrf':csrf}).status_code==303
    row=episode(eid)
    assert row['status']=='pending' and row['attempts']==0 and row['available_at'] is None and row['lease_until'] is None and row['error'] is None
    assert row['transcript']=='Preserved original transcript'
    assert client.post('/admin/action',data={'action':'retry','target_type':'episode','target':ready,'csrf':csrf}).status_code==303
    assert episode(ready)['status']=='ready' and episode(ready)['attempts']==2
