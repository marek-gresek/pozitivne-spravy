"""One AI worker; independent maintenance thread keeps hourly expiry even during inference."""
import argparse
import fcntl
import json
import logging
import os
import signal
import threading
import time
import uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from database import init_db,connect,utcnow,setting,set_setting,DB_FILE
from pipeline import collect_feeds,process_queue,register_sources,normalize_legacy_urls
from curation import select_candidates
from podcasts import ensure_episodes,process_episodes,cleanup_audio

stop=threading.Event()
logger=logging.getLogger(__name__)

def run_record(kind,window,fn):
    rid=str(uuid.uuid4())
    try:
        with connect() as c:c.execute('INSERT INTO job_runs(id,kind,window,status,started_at) VALUES(?,?,?,?,?)',(rid,kind,window,'running',utcnow()))
        result=fn()
        with connect() as c:c.execute("UPDATE job_runs SET status='success',finished_at=? WHERE id=?",(utcnow(),rid))
        return result
    except Exception as error:
        # Reporting must still work when the database itself is unavailable.
        # Log only the error class, never provider responses or credentials.
        logger.error('Job %s failed (%s)',kind,type(error).__name__)
        try:
            with connect() as c:c.execute("UPDATE job_runs SET status='failed',finished_at=?,error='job_failed' WHERE id=?",(utcnow(),rid))
        except Exception as recording_error:
            logger.error('Job status unavailable (%s)',type(recording_error).__name__)
        return None

def maintenance():
    while not stop.is_set():
        # The entire cycle owns recovery, including status/heartbeat writes.
        # A failed cycle retries promptly without killing this daemon thread.
        delay=60
        try:
            cleanup_result=run_record('cleanup',utcnow(),cleanup_audio)
            # Database-only backups; never include audio. Keep fourteen daily snapshots.
            now=datetime.now(timezone.utc); day=now.date().isoformat()
            if setting('last_backup_day','')!=day:
                import sqlite3
                dest=Path(DB_FILE).parent/'backups';dest.mkdir(exist_ok=True)
                target=dest/(day+'.sqlite3')
                with connect() as source:
                    backup=sqlite3.connect(target)
                    try:source.backup(backup)
                    finally:backup.close()
                set_setting('last_backup_day',day)
                for path in dest.glob('*.sqlite3'):
                    if not path.is_symlink() and path.stat().st_mtime<time.time()-14*86400:path.unlink()
            # Scoped one-time legacy audio bundle authorized for seven successful pilot days.
            bundle=setting('legacy_audio_bundle',''); started=setting('pilot_started_at','')
            if bundle and started:
                date=datetime.fromisoformat(started)
                with connect() as c:
                    days=c.execute("SELECT count(DISTINCT e.day) FROM episodes e WHERE e.status IN ('ready','expired') AND (SELECT count(DISTINCT x.kind) FROM episodes x WHERE x.day=e.day AND x.status IN ('ready','expired'))=2 AND EXISTS(SELECT 1 FROM job_runs j WHERE j.kind='rss' AND j.status='success' AND substr(j.finished_at,1,10)=e.day)").fetchone()[0]
                if now-date>=timedelta(days=7) and days>=7:
                    p=Path(bundle)
                    # This directory lives in the worker's existing /data mount.
                    # A host-only path would silently miss the actual recovery archive.
                    allowed=Path(DB_FILE).parent/'recovery-audio'
                    if p==allowed/'legacy-audio.tar.gz' and not allowed.is_symlink() and not p.is_symlink():
                        fd=os.open(allowed,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
                        try:
                            try:os.unlink(p.name,dir_fd=fd)
                            except FileNotFoundError:pass
                        finally:os.close(fd)
                        set_setting('legacy_audio_bundle','')
            set_setting('maintenance_error','cleanup_failed' if cleanup_result is None else '')
            set_setting('worker_heartbeat',utcnow())
            if cleanup_result is not None:delay=3600
        except Exception as error:
            logger.error('Maintenance cycle failed (%s)',type(error).__name__)
            try:set_setting('maintenance_error','backup_or_retention_failed')
            except Exception as recording_error:
                logger.error('Maintenance status unavailable (%s)',type(recording_error).__name__)
        stop.wait(delay)

def schedule_podcast_days(now):
    """Persist every due calendar day, even while inference is paused or blocked."""
    zone=ZoneInfo('Europe/Prague')
    first=datetime.fromisoformat(setting('pilot_started_at')).astimezone(zone).date()-timedelta(days=1)
    latest=now.date()-timedelta(days=1 if now.hour>=9 else 2)
    cursor=setting('last_scheduled_podcast_day')
    day=datetime.fromisoformat(cursor).date()+timedelta(days=1) if cursor else first
    if day>latest:return
    with connect() as c:
        while day<=latest:
            c.execute('INSERT OR IGNORE INTO podcast_days(day,created_at) VALUES(?,?)',(day.isoformat(),utcnow()))
            day+=timedelta(days=1)
        c.execute("INSERT INTO settings VALUES('last_scheduled_podcast_day',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(latest.isoformat(),))

def ready_podcast_days():
    zone=ZoneInfo('Europe/Prague');ready=set()
    with connect() as c:
        days=[r['day'] for r in c.execute("SELECT day FROM podcast_days WHERE status='waiting' ORDER BY day")]
        for day in days:
            start=datetime.fromisoformat(day).replace(tzinfo=zone)
            end=start+timedelta(days=1)
            pending=c.execute("SELECT count(*) FROM tasks WHERE state IN ('pending','processing') AND json_extract(CASE WHEN json_valid(payload) THEN payload ELSE '{}' END,'$.published_at')>=? AND json_extract(CASE WHEN json_valid(payload) THEN payload ELSE '{}' END,'$.published_at')<?",(start.astimezone(timezone.utc).isoformat(timespec='seconds'),end.astimezone(timezone.utc).isoformat(timespec='seconds'))).fetchone()[0]
            if not pending:ready.add(day)
    return ready

def run():
    init_db();register_sources();normalize_legacy_urls()
    if not setting('pilot_started_at'):set_setting('pilot_started_at',datetime.now(timezone.utc).isoformat(timespec='seconds'))
    maintenance_thread=threading.Thread(target=maintenance,daemon=True);maintenance_thread.start()
    while not stop.is_set():
        now=datetime.now(ZoneInfo('Europe/Prague'))
        slot=f'{now.date()}-{now.hour//2:02d}-{now.utcoffset()}'
        if setting('last_rss_slot','')!=slot:
            result=run_record('rss',slot,collect_feeds)
            if result is not None:set_setting('last_rss_slot',slot)
        schedule_podcast_days(now)
        if setting('pipeline_paused','0')!='1':
            select_candidates(now)
            run_record('articles',slot,lambda:process_queue(max_batches=1))
            eligible=ready_podcast_days()
            if eligible:
                for day in sorted(eligible):ensure_episodes(day);set_setting('last_episode_day',day)
                run_record('podcasts',','.join(sorted(eligible)),lambda:process_episodes(allowed_days=eligible))
                with connect() as c:
                    for day in eligible:
                        complete=c.execute("SELECT count(DISTINCT kind) FROM episodes WHERE day=? AND status IN ('ready','expired')",(day,)).fetchone()[0]
                        if complete==2:c.execute("UPDATE podcast_days SET status='complete',completed_at=? WHERE day=?",(utcnow(),day))
        set_setting('worker_heartbeat',utcnow());stop.wait(20)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',nargs='?',default='run',choices=['run','collect','process','podcasts','cleanup','init'])
    parser.add_argument('--day');parser.add_argument('--batches',type=int,default=1);args=parser.parse_args()
    init_db();Path(DB_FILE).parent.mkdir(parents=True,exist_ok=True)
    lockpath=Path(DB_FILE).parent/'worker.lock'
    if args.command in ('collect','cleanup','init'):
        if args.command=='collect':print('queued',collect_feeds())
        elif args.command=='cleanup':print('removed_bytes',cleanup_audio())
        return
    with lockpath.open('a+') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('worker_already_running')
        if args.command=='run':run()
        elif args.command=='process':
            select_candidates();print('processed',process_queue(max_batches=args.batches))
        else:
            select_candidates();ensure_episodes(args.day);print('episodes',process_episodes())

if __name__=='__main__':
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    main()
