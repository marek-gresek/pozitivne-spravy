"""Offline tests at the worker scheduling seam; no background thread or network."""
import json
import os
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
import database
import worker

PRAGUE=ZoneInfo('Europe/Prague')
UTC=timezone.utc


@pytest.fixture
def db(tmp_path,monkeypatch):
    path=tmp_path/'test.db'
    monkeypatch.setattr(database,'DB_FILE',str(path))
    monkeypatch.setattr(worker,'DB_FILE',str(path))
    database.init_db()
    return tmp_path


def add_article(article_id='one'):
    with database.connect() as c:
        c.execute('INSERT INTO clanky(id,nadpis,link,zhrnutie,sentiment,published_at,topic) VALUES(?,?,?,?,?,?,?)',
                  (article_id,'Distinct story '+article_id,'https://example.org/'+article_id,'Verified summary','Pozitívny','2026-10-02T10:00:00+00:00','Veda a technológie'))


def add_task(article_id='pending',published_at='2026-10-02T10:00:00+00:00'):
    with database.connect() as c:
        c.execute('INSERT INTO tasks(id,payload,created_at,updated_at) VALUES(?,?,?,?)',
                  (article_id,json.dumps({'published_at':published_at}),database.utcnow(),database.utcnow()))


def run_loops(monkeypatch,times,article_action=None):
    calls={'rss':0,'articles':0,'podcasts':0,'threads':[]}
    class Stop:
        index=0
        def is_set(self):return self.index>=len(times)
        def wait(self,seconds):
            assert seconds==20
            self.index+=1
    stop=Stop()
    class Frozen(datetime):
        @classmethod
        def now(cls,tz=None):return times[min(stop.index,len(times)-1)].astimezone(tz or UTC)
    class Thread:
        def __init__(self,**kwargs):calls['threads'].append(kwargs)
        def start(self):pass
    def collect():calls['rss']+=1;return 0
    def process(**kwargs):
        assert kwargs=={'max_batches':1}
        calls['articles']+=1
        if article_action:article_action(calls['articles'])
        return 0
    def podcasts(**kwargs):calls['podcasts']+=1;return 0
    monkeypatch.setattr(worker,'stop',stop)
    monkeypatch.setattr(worker,'datetime',Frozen)
    monkeypatch.setattr(worker.threading,'Thread',Thread)
    monkeypatch.setattr(worker,'collect_feeds',collect)
    monkeypatch.setattr(worker,'process_queue',process)
    monkeypatch.setattr(worker,'process_episodes',podcasts)
    worker.run()
    return calls


def at(hour,minute=0):return datetime(2026,10,3,hour,minute,tzinfo=PRAGUE)


def test_podcasts_wait_for_previous_day_articles_then_ensure_after_completion(db,monkeypatch):
    add_task()
    def finish(iteration):
        if iteration==1:
            with database.connect() as c:assert c.execute('SELECT count(*) FROM episodes').fetchone()[0]==0
            assert database.setting('last_episode_day') is None
        elif iteration==2:
            add_article()
            with database.connect() as c:c.execute("UPDATE tasks SET state='done' WHERE id='pending'")
    calls=run_loops(monkeypatch,[at(9),at(9,1)],finish)
    assert calls['podcasts']==1
    assert database.setting('last_episode_day')=='2026-10-02'
    with database.connect() as c:
        assert {tuple(r) for r in c.execute('SELECT kind,day FROM episodes')}=={('positive','2026-10-02'),('all','2026-10-02')}


def test_empty_day_can_become_populated_after_initial_ensure(db,monkeypatch):
    def later_article(iteration):
        if iteration==2:add_article()
    calls=run_loops(monkeypatch,[at(9),at(9,1),at(9,2)],later_article)
    assert calls['podcasts']==3
    with database.connect() as c:assert c.execute('SELECT count(*) FROM episodes').fetchone()[0]==2


def test_only_previous_prague_calendar_day_pending_tasks_block_podcasts(db,monkeypatch):
    add_article()
    # Calendar window: previous local midnight=Oct1 22:00Z, current midnight=Oct2 22:00Z.
    add_task('older','2026-10-01T21:59:59+00:00')
    add_task('current','2026-10-02T22:00:00+00:00')
    calls=run_loops(monkeypatch,[at(9)])
    assert calls['podcasts']==1


def test_midnight_boundary_inside_previous_day_blocks_podcasts(db,monkeypatch):
    add_article();add_task('start','2026-10-01T22:00:00+00:00')
    calls=run_loops(monkeypatch,[at(9)])
    assert calls['podcasts']==0
    with database.connect() as c:assert c.execute('SELECT count(*) FROM episodes').fetchone()[0]==0

def test_due_day_survives_backlog_and_restart_across_midnight(db,monkeypatch):
    add_task()
    first=run_loops(monkeypatch,[at(9)])
    assert first['podcasts']==0
    with database.connect() as c:assert c.execute('SELECT day FROM podcast_days').fetchone()[0]=='2026-10-02'
    def finish(iteration):
        add_article()
        with database.connect() as c:c.execute("UPDATE tasks SET state='done' WHERE id='pending'")
    second=run_loops(monkeypatch,[datetime(2026,10,4,8,tzinfo=PRAGUE)],finish)
    assert second['podcasts']==1
    with database.connect() as c:
        assert {tuple(r) for r in c.execute('SELECT kind,day FROM episodes')}=={('positive','2026-10-02'),('all','2026-10-02')}
        assert {r['day'] for r in c.execute('SELECT day FROM podcast_days')}=={'2026-10-02'}

def test_pause_persists_due_days_for_catchup_after_multiple_days(db,monkeypatch):
    database.set_setting('pipeline_paused','1')
    run_loops(monkeypatch,[at(9),datetime(2026,10,5,9,tzinfo=PRAGUE)])
    with database.connect() as c:assert {r['day'] for r in c.execute('SELECT day FROM podcast_days')}=={'2026-10-02','2026-10-03','2026-10-04'}


def test_before_nine_podcasts_stay_pending_and_rss_runs_once_per_two_hour_slot(db,monkeypatch):
    add_article()
    calls=run_loops(monkeypatch,[at(8,59),at(9),at(9,59),at(10)])
    assert calls['rss']==2 and calls['articles']==4 and calls['podcasts']==3
    assert len(calls['threads'])==1 and calls['threads'][0]['target']==worker.maintenance
    assert calls['threads'][0]['daemon'] is True
    with database.connect() as c:assert c.execute('SELECT count(*) FROM episodes').fetchone()[0]==2


def test_pause_prevents_inference_but_keeps_rss_and_maintenance_dispatch(db,monkeypatch):
    add_article();database.set_setting('pipeline_paused','1')
    calls=run_loops(monkeypatch,[at(9)])
    assert calls['rss']==1 and calls['articles']==calls['podcasts']==0
    assert calls['threads'][0]['target']==worker.maintenance


def test_job_failure_is_sanitized_and_recorded(db):
    def broken():raise RuntimeError('PRIVATE secret prompt credentials')
    assert worker.run_record('articles','window',broken) is None
    with database.connect() as c:row=dict(c.execute('SELECT * FROM job_runs').fetchone())
    assert row['status']=='failed' and row['error']=='job_failed' and row['finished_at']
    assert 'PRIVATE' not in str(row)


def maintenance_once(monkeypatch):
    class Stop:
        complete=False
        def is_set(self):return self.complete
        def wait(self,seconds):assert seconds==3600;self.complete=True
    monkeypatch.setattr(worker,'stop',Stop())
    monkeypatch.setattr(worker,'cleanup_audio',lambda:0)
    worker.maintenance()


def test_daily_sqlite_backup_is_audio_free_and_retains_only_recent_owned_snapshots(db,monkeypatch):
    import sqlite3
    add_article();audio=db/'audio';audio.mkdir();(audio/'speech.mp3').write_bytes(b'audio not in database backup')
    backups=db/'backups';backups.mkdir()
    old=backups/'2020-01-01.sqlite3';old.write_bytes(b'old')
    recent=backups/'recent.sqlite3';recent.write_bytes(b'recent')
    foreign=db/'foreign.sqlite3';foreign.write_bytes(b'foreign');symlink=backups/'link.sqlite3';symlink.symlink_to(foreign)
    past=datetime.now(UTC).timestamp()-15*86400;os.utime(old,(past,past))
    maintenance_once(monkeypatch)
    today=backups/(datetime.now(UTC).date().isoformat()+'.sqlite3')
    assert today.exists() and recent.exists() and not old.exists()
    assert symlink.is_symlink() and foreign.read_bytes()==b'foreign'
    with sqlite3.connect(today) as c:assert c.execute('SELECT count(*) FROM clanky').fetchone()[0]==1
    assert (audio/'speech.mp3').exists()
    assert database.setting('last_backup_day')==datetime.now(UTC).date().isoformat()


def test_cleanup_error_does_not_prevent_daily_backup(db,monkeypatch):
    def broken():raise PermissionError('private filesystem detail')
    monkeypatch.setattr(worker,'cleanup_audio',broken)
    class Stop:
        complete=False
        def is_set(self):return self.complete
        def wait(self,seconds):self.complete=True
    monkeypatch.setattr(worker,'stop',Stop());worker.maintenance()
    with database.connect() as c:assert tuple(c.execute("SELECT status,error FROM job_runs WHERE kind='cleanup'").fetchone())==('failed','job_failed')
    assert database.setting('last_backup_day')


@pytest.mark.parametrize('filename,command',[('spracuj_clanky.py','process'),('script_podcast.py','podcasts'),('vytvor_podcasty.py','podcasts')])
def test_retired_scripts_delegate_only_to_current_worker(monkeypatch,filename,command):
    import runpy
    import sys
    calls=[]
    monkeypatch.setattr(worker,'main',lambda:calls.append(list(sys.argv)))
    monkeypatch.setattr(sys,'argv',[filename,'old-argument'])
    runpy.run_path(str(Path(__file__).resolve().parent.parent/filename),run_name='__main__')
    assert calls==[[str(Path(__file__).resolve().parent.parent/filename),command]]


def test_legacy_audio_retention_rejects_symlinked_parent_outside_allowed_root(db,monkeypatch):
    outside=db/'outside';outside.mkdir()
    external=outside/'legacy-audio.tar.gz';external.write_bytes(b'outside protected scope')
    alias=db/'recovery-audio';alias.symlink_to(outside,target_is_directory=True)
    bundle=alias/'legacy-audio.tar.gz'
    database.set_setting('legacy_audio_bundle',str(bundle))
    database.set_setting('pilot_started_at',(datetime.now(UTC)-timedelta(days=8)).isoformat(timespec='seconds'))
    with database.connect() as c:
        for i in range(7):
            stamp=(datetime.now(UTC)-timedelta(days=i)).isoformat(timespec='seconds')
            c.execute('INSERT INTO job_runs(id,kind,status,started_at,finished_at) VALUES(?,?,?,?,?)',(str(i),'rss','success',stamp,stamp))
            for kind in ('positive','all'):
                c.execute('INSERT INTO episodes(id,kind,day,title,status,created_at) VALUES(?,?,?,?,?,?)',(str(i)+kind,kind,stamp[:10],'Qualified episode','ready',stamp))
    maintenance_once(monkeypatch)
    assert external.read_bytes()==b'outside protected scope'
    assert database.setting('legacy_audio_bundle')==str(bundle)


@pytest.mark.parametrize('qualified_days,elapsed_days,expected_deleted',[(6,8,False),(7,6,False),(7,8,True)])
def test_legacy_bundle_requires_seven_completed_editions_and_seven_elapsed_days(db,monkeypatch,qualified_days,elapsed_days,expected_deleted):
    folder=db/'recovery-audio';folder.mkdir()
    bundle=folder/'legacy-audio.tar.gz';bundle.write_bytes(b'authorized archive')
    database.set_setting('legacy_audio_bundle',str(bundle))
    database.set_setting('pilot_started_at',(datetime.now(UTC)-timedelta(days=elapsed_days)).isoformat(timespec='seconds'))
    with database.connect() as c:
        for i in range(7):
            stamp=(datetime.now(UTC)-timedelta(days=i)).isoformat(timespec='seconds')
            c.execute('INSERT INTO job_runs(id,kind,status,started_at,finished_at) VALUES(?,?,?,?,?)',(str(i),'rss','success',stamp,stamp))
            for kind in ('positive','all'):
                status='ready' if i<qualified_days else ('ready' if kind=='positive' else 'failed')
                c.execute('INSERT INTO episodes(id,kind,day,title,status,created_at) VALUES(?,?,?,?,?,?)',(str(i)+kind,kind,stamp[:10],'Qualified episode',status,stamp))
    maintenance_once(monkeypatch)
    assert bundle.exists() is not expected_deleted
    assert database.setting('legacy_audio_bundle')==('' if expected_deleted else str(bundle))


def test_bounded_launcher_applies_ceiling_before_executing_command(monkeypatch):
    import runpy
    import resource
    import sys
    operations=[]
    monkeypatch.setenv('MEMORY_CEILING_MB','768')
    monkeypatch.setattr(resource,'setrlimit',lambda limit,bounds:operations.append(('limit',limit,bounds)))
    monkeypatch.setattr(os,'execvp',lambda command,args:operations.append(('exec',command,args)))
    monkeypatch.setattr(sys,'argv',['bounded_service.py','python','worker.py','run'])
    runpy.run_path(str(Path(__file__).resolve().parent.parent/'bounded_service.py'),run_name='__main__')
    assert operations==[('limit',resource.RLIMIT_AS,(768*1024*1024,768*1024*1024)),('exec','python',['python','worker.py','run'])]


def test_scheduler_handles_malformed_pending_payload_while_claiming_is_postponed(db,monkeypatch):
    add_article()
    with database.connect() as c:
        c.execute('INSERT INTO tasks(id,payload,created_at,updated_at) VALUES(?,?,?,?)',('corrupt','not-json',database.utcnow(),database.utcnow()))
    database.set_setting('quota_until',(datetime.now(UTC)+timedelta(hours=1)).isoformat(timespec='seconds'))
    # During quota process_queue returns before claim_tasks can quarantine corruption.
    calls=run_loops(monkeypatch,[at(9)])
    assert calls['articles']==1
    assert database.setting('worker_heartbeat')
