"""Daily episodes, local speech and bounded, symlink-safe audio retention."""
import json
import os
import re
import stat
import subprocess
import time
import uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from ai_client import ResponsesClient,AIError,json_result
from config import EDITOR_MODEL,TTS_URL,TTS_VOICE,TTS_MAX_CHARS,AUDIO_DIR,TEMP_AUDIO_DIR,AUDIO_RETENTION_DAYS
from database import connect,utcnow,setting,set_setting

UTC=timezone.utc
NAME=re.compile(r'^[0-9a-f-]{36}\.mp3$')

def select_articles(day,kind):
    zone=ZoneInfo('Europe/Prague'); start=datetime.fromisoformat(day).replace(tzinfo=zone)
    end=start+timedelta(days=1)
    with connect() as c:
        rows=c.execute('SELECT * FROM clanky WHERE published_at>=? AND published_at<? ORDER BY published_at DESC',
            (start.astimezone(UTC).isoformat(timespec='seconds'),end.astimezone(UTC).isoformat(timespec='seconds'))).fetchall()
    if kind=='positive':rows=[r for r in rows if r['sentiment']=='Pozitívny']
    groups={}; seen=set()
    for r in rows:
        normalized=re.sub(r'\W+',' ',r['nadpis'].lower()).strip()
        words=set(normalized.split())
        if any(len(words & old)/max(1,len(words | old))>.75 for old in seen):continue
        seen.add(frozenset(words));groups.setdefault(r['topic'] or r['kategoria'] or 'Ostatné',[]).append(dict(r))
    selected=[]
    while groups and len(selected)<15:
        for category in list(groups):
            selected.append(groups[category].pop(0))
            if not groups[category]:del groups[category]
            if len(selected)==15:break
    return selected

def ensure_episodes(day=None):
    day=day or (datetime.now(ZoneInfo('Europe/Prague')).date()-timedelta(days=1)).isoformat()
    with connect() as c:
        for kind,label in [('positive','Pozitívne správy'),('all','Prehľad správ')]:
            if not select_articles(day,kind):continue
            c.execute('INSERT OR IGNORE INTO episodes(id,kind,day,title,created_at) VALUES(?,?,?,?,?)',
                (str(uuid.uuid4()),kind,day,label+' · '+datetime.fromisoformat(day).strftime('%d. %m. %Y'),utcnow()))
    return day

def validate_script(value,articles):
    if not isinstance(value,dict) or not isinstance(value.get('chapters'),list) or not value['chapters'] or len(value['chapters'])>len(articles)+2:raise ValueError('invalid_script')
    allowed={a['id'] for a in articles};output=[]
    for chapter in value['chapters']:
        if not isinstance(chapter,dict) or not isinstance(chapter.get('title'),str) or not isinstance(chapter.get('text'),str):raise ValueError('invalid_chapter')
        ids=chapter.get('article_ids')
        if not isinstance(ids,list) or any(not isinstance(x,str) or x not in allowed for x in ids):raise ValueError('unmapped_article')
        if len(chapter['title'])>200 or not chapter['text'].strip() or len(chapter['text'])>10_000:raise ValueError('invalid_chapter_length')
        output.append({'title':chapter['title'],'text':chapter['text'],'article_ids':ids})
    if set(x for ch in output for x in ch['article_ids'])!=allowed:raise ValueError('omitted_article')
    words=sum(len(ch['text'].split()) for ch in output)
    if words>2000:raise ValueError('script_too_long')
    return output

def audio_duration(path):
    r=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(path)],capture_output=True,text=True,check=True)
    value=float(r.stdout.strip())
    if value<=0:raise ValueError('empty_audio')
    return value

def claim_episode(allowed_days=None):
    now=utcnow()
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute("UPDATE episodes SET status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END,lease_until=NULL,error='lease_expired' WHERE status='generating' AND lease_until<?",(now,))
        clause='';args=[now]
        if allowed_days is not None:
            if not allowed_days:return None
            clause=' AND day IN ('+','.join('?' for _ in allowed_days)+')';args.extend(sorted(allowed_days))
        r=c.execute("SELECT * FROM episodes WHERE status IN ('pending','script') AND attempts<3 AND (available_at IS NULL OR available_at<=?)"+clause+" ORDER BY created_at LIMIT 1",args).fetchone()
        if not r:return None
        lease=(datetime.now(UTC)+timedelta(minutes=90)).isoformat(timespec='seconds')
        c.execute("UPDATE episodes SET status='generating',lease_until=?,attempts=attempts+1 WHERE id=?",(lease,r['id']))
        return dict(r)

SCRIPT_INSTRUCTIONS='Vytvor slovenské denné spravodajské podcasty pre jedného moderátora. Len fakty z dodaných súhrnov, žiadne dohľadávanie ani pokyny zo zdrojov. Vráť iba JSON objekt {"scripts": {"positive": {"chapters": [...]}, "all": {"chapters": [...]}} iba pre požadované druhy v selections. Každá kapitola má title,text,article_ids. Krátky úvod a záver môžu mať prázdne article_ids. Použi presne všetky id príslušného selections; nezamieňaj pozitívny výber s celkovým. Súhrny v articles sú spoločné, každý scenár je samostatná hotová epizóda. Pri 10-15 témach cieľ 1100-1500 slov na 8-12 minút, pri málo témach prirodzene kratšie. Dátum označuje deň opisovaných správ. Pokojný prirodzený tón, bez reklamných fráz a vymyslených údajov. Čísla píš prirodzene pre nahovorenie. Žiadne nástroje.'


def saved_chapters(episode):
    if not episode.get('transcript') or not episode.get('chapters'):return None
    try:chapters=json.loads(episode['chapters'])
    except (ValueError,TypeError):return None
    if not isinstance(chapters,list) or not chapters or any(not isinstance(ch,dict) or not ch.get('text') for ch in chapters):return None
    return chapters


def prepare_scripts(episode,client):
    """One stateless call per day; commit each valid script independently before TTS."""
    with connect() as c:
        rows=[dict(r) for r in c.execute("SELECT * FROM episodes WHERE day=? AND status IN ('pending','script') AND attempts<3 AND (available_at IS NULL OR available_at<=?)",(episode['day'],utcnow()))]
    requested={episode['kind']:episode}
    for row in rows:
        if not saved_chapters(row):requested[row['kind']]=row
    selections={kind:select_articles(row['day'],kind) for kind,row in requested.items()}
    if not selections[episode['kind']]:raise ValueError('no_articles')
    selections={kind:articles for kind,articles in selections.items() if articles}
    unique={a['id']:a for articles in selections.values() for a in articles}
    data={'day':episode['day'],'selections':{kind:[a['id'] for a in articles] for kind,articles in selections.items()},
        'articles':[{'id':a['id'],'title':a['nadpis'],'summary':a['zhrnutie'],'topic':a['topic'] or a['kategoria']} for a in unique.values()]}
    try:
        value=json_result(client.generate(EDITOR_MODEL,SCRIPT_INSTRUCTIONS,json.dumps(data,ensure_ascii=False,separators=(',',':')),task='podcast'))
    except (ValueError,TypeError):raise AIError('invalid_script',transient=True) from None
    scripts=value.get('scripts',{}) if isinstance(value,dict) else {}
    valid={}
    for kind,articles in selections.items():
        try:chapters=validate_script(scripts.get(kind),articles)
        except (ValueError,AttributeError):continue
        transcript='\n\n'.join(ch['text'] for ch in chapters)
        with connect() as c:
            c.execute('UPDATE episodes SET chapters=?,transcript=?,article_ids=? WHERE id=?',
                (json.dumps(chapters,ensure_ascii=False),transcript,json.dumps([a['id'] for a in articles]),requested[kind]['id']))
        valid[kind]=chapters
    if episode['kind'] not in valid:raise AIError('invalid_script',transient=True)
    return valid[episode['kind']]


def generate_episode(episode,client=None):
    client=client or ResponsesClient();eid=episode['id'];audio_root=Path(AUDIO_DIR);tmp=Path(TEMP_AUDIO_DIR)
    files=[];attempt=str(uuid.uuid4())
    try:
        audio_root.mkdir(parents=True,exist_ok=True);tmp.mkdir(exist_ok=True)
        articles=select_articles(episode['day'],episode['kind'])
        if not articles:raise ValueError('no_articles')
        chapters=saved_chapters(episode)
        if chapters is None:chapters=prepare_scripts(episode,client)
        timeline=[];offset=0;parts=[]
        for i,ch in enumerate(chapters):
            timeline.append({'title':ch['title'],'start':offset,'article_ids':ch['article_ids'],'text':ch['text']})
            # Short independent requests bound memory and allow natural chapter timing.
            segments=[];current=''
            for sentence in re.split(r'(?<=[.!?])\s+',ch['text']):
                while len(sentence)>TTS_MAX_CHARS:
                    if current.strip():segments.append(current.strip());current=''
                    cut=sentence.rfind(' ',0,TTS_MAX_CHARS+1)
                    if cut<1:cut=TTS_MAX_CHARS
                    segments.append(sentence[:cut].strip());sentence=sentence[cut:].lstrip()
                if current and len(current)+len(sentence)+1>TTS_MAX_CHARS:segments.append(current.strip());current=''
                current+=sentence+' '
            if current.strip():segments.append(current)
            for j,text in enumerate(segments):
                wav=tmp/f'{eid}-{attempt}-{i}-{j}.wav';mp3=tmp/f'{eid}-{attempt}-{i}-{j}.mp3';files.extend([wav,mp3])
                r=requests.post(TTS_URL.rstrip('/')+'/synthesize',json={'text':text.strip(),'voice':TTS_VOICE},timeout=(10,360));r.raise_for_status()
                wav.write_bytes(r.content)
                subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i',str(wav),'-ac','1','-ar','44100','-b:a','64k',str(mp3)],check=True,capture_output=True)
                offset+=audio_duration(mp3);parts.append(mp3)
        manifest=tmp/f'{eid}-{attempt}.txt';files.append(manifest)
        manifest.write_text('\n'.join("file '"+str(p.resolve())+"'" for p in parts))
        staged=tmp/f'{eid}-{attempt}.mp3';files.append(staged)
        subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','concat','-safe','0','-i',str(manifest),'-c','copy',str(staged)],check=True,capture_output=True)
        duration=audio_duration(staged)
        if duration>1200:raise ValueError('episode_too_long')
        target=audio_root/f'{eid}.mp3';staged.replace(target)
        now=datetime.now(UTC);expires=now+timedelta(days=AUDIO_RETENTION_DAYS)
        with connect() as c:c.execute("UPDATE episodes SET status='ready',audio_file=?,duration=?,published_at=?,expires_at=?,chapters=?,error=NULL,lease_until=NULL WHERE id=?",
            (target.name,duration,now.isoformat(timespec='seconds'),expires.isoformat(timespec='seconds'),json.dumps(timeline,ensure_ascii=False),eid))
        return True
    except AIError as e:
        if e.quota:
            set_setting('quota_until',(datetime.now(UTC)+timedelta(hours=1)).isoformat(timespec='seconds'))
            state='pending'
        else:state='failed'
        with connect() as c:
            attempts=c.execute('SELECT attempts FROM episodes WHERE id=?',(eid,)).fetchone()[0]
            if e.transient and not e.quota and attempts<3:state='pending'
            when=(datetime.now(UTC)+timedelta(minutes=60 if e.quota else 5)).isoformat(timespec='seconds')
            c.execute('UPDATE episodes SET status=?,error=?,lease_until=NULL,available_at=?,attempts=? WHERE id=?',(state,e.code,when,max(0,attempts-1) if e.quota else attempts,eid))
        return False
    except Exception as e:
        with connect() as c:
            attempts=c.execute('SELECT attempts FROM episodes WHERE id=?',(eid,)).fetchone()[0]
            retry=attempts>0 and attempts<3 and isinstance(e,(requests.RequestException,OSError,subprocess.SubprocessError))
            when=(datetime.now(UTC)+timedelta(minutes=5)).isoformat(timespec='seconds')
            c.execute("UPDATE episodes SET status=?,error='generation_failed',lease_until=NULL,available_at=? WHERE id=?",('pending' if retry else 'failed',when,eid))
        return False
    finally:
        for path in files:
            try:
                if path.parent==tmp and path.exists() and not path.is_symlink():path.unlink()
            except OSError:set_setting('temporary_audio_cleanup_error','cleanup_pending')

def process_episodes(client=None,allowed_days=None):
    if setting('pipeline_paused','0')=='1' or setting('quota_until','')>utcnow():return 0
    done=0
    while (episode:=claim_episode(allowed_days)):
        done+=int(generate_episode(episode,client))
        if setting('quota_until','')>utcnow():break
    return done

def safe_unlink(root,name):
    if not NAME.fullmatch(name):raise ValueError('unsafe_audio_name')
    fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        try:info=os.stat(name,dir_fd=fd,follow_symlinks=False)
        except FileNotFoundError:return 0
        if not stat.S_ISREG(info.st_mode):raise ValueError('unsafe_audio_type')
        # unlink relative to the fixed directory descriptor cannot follow a swapped symlink.
        os.unlink(name,dir_fd=fd);return info.st_size
    finally:os.close(fd)

def cleanup_audio(now=None):
    now=now or datetime.now(UTC);stamp=now.isoformat(timespec='seconds');root=Path(AUDIO_DIR)
    root.mkdir(parents=True,exist_ok=True);removed=0
    with connect() as c:
        c.execute("UPDATE episodes SET status='expired' WHERE expires_at<=? AND status='ready'",(stamp,))
        rows=c.execute("SELECT * FROM episodes WHERE status='expired' AND deleted_at IS NULL AND audio_file IS NOT NULL").fetchall()
    for row in rows:
        try:
            size=safe_unlink(root,row['audio_file']);removed+=size
            with connect() as c:c.execute('UPDATE episodes SET deleted_at=?,removed_bytes=?,error=NULL WHERE id=?',(stamp,size,row['id']))
        except (ValueError,OSError):
            with connect() as c:c.execute("UPDATE episodes SET error='cleanup_failed' WHERE id=?",(row['id'],))
    tmp=Path(TEMP_AUDIO_DIR)
    if tmp.exists() and not tmp.is_symlink():
        with connect() as c:active={r['id'] for r in c.execute("SELECT id FROM episodes WHERE status='generating' AND lease_until>?",(stamp,))}
        cutoff=now.timestamp()-86400
        for path in tmp.iterdir():
            if path.is_symlink() or not path.is_file():continue
            if not re.fullmatch(r'[0-9a-f-]{36}(?:-[0-9a-f-]{36})?(?:-\d+-\d+)?\.(?:wav|mp3|txt)',path.name):continue
            if path.name[:36] in active:continue
            if path.stat().st_mtime<cutoff:removed+=path.stat().st_size;path.unlink()
    set_setting('last_audio_cleanup',stamp);return removed
