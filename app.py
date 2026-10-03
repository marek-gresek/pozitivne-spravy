"""Minimal Slovak reader and private operations view."""
import hmac
import json
import os
import re
import secrets
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from flask import Flask, Response, abort, redirect, render_template, request, send_file, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
import database
import config
from security import access_required
from web_queries import article, json_list, list_articles


def parsed_time(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, AttributeError): return None

def live_audio(episode):
    expires = parsed_time(episode.get('expires_at'))
    filename = episode.get('audio_file')
    if episode.get('status') != 'ready' or not expires or expires <= datetime.now(timezone.utc) or not filename:
        return None
    if not isinstance(filename,str) or not re.fullmatch(r'[0-9a-f-]{36}\.mp3',filename): return None
    root = config.AUDIO_DIR
    if root.is_symlink(): return None
    candidate = root / filename
    if candidate.is_symlink(): return None
    base = root.resolve()
    path = candidate.resolve()
    if path.parent != base or not path.is_file(): return None
    return path

def episode_view(row):
    ep = dict(row); ep['chapters'] = json_list(ep.get('chapters')); ep['article_ids'] = json_list(ep.get('article_ids'))
    ep['available'] = bool(live_audio(ep))
    expires = parsed_time(ep.get('expires_at'))
    ep['expired'] = ep.get('status') == 'expired' or bool(expires and expires <= datetime.now(timezone.utc))
    return ep

def create_app():
    app = Flask(__name__)
    # The immediate Cloudflare tunnel forwards the original public scheme.
    # Identity is independently verified by signed Access JWTs, never proxy headers.
    app.wsgi_app = ProxyFix(app.wsgi_app,x_for=0,x_proto=1,x_host=0,x_port=0,x_prefix=0)
    app.config.update(SECRET_KEY=os.getenv('SECRET_KEY') or secrets.token_hex(32), SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SECURE=True, SESSION_COOKIE_SAMESITE='Lax', MAX_CONTENT_LENGTH=16384)
    database.init_db()

    @app.template_filter('skdate')
    def skdate(value, full=False):
        dt=parsed_time(value)
        return dt.astimezone(ZoneInfo('Europe/Prague')).strftime('%d. %m. %Y · %H:%M' if full else '%d. %m. %Y') if dt else 'Dátum neuvedený'

    @app.template_filter('clock')
    def clock(value):
        try: seconds=max(0,int(float(value or 0)))
        except (ValueError,TypeError): seconds=0
        return f'{seconds//60}:{seconds%60:02d}'

    @app.template_filter('safeurl')
    def safeurl(value):
        try:
            parts=urlsplit(value or '')
            return value if parts.scheme in ('http','https') and parts.netloc else '#'
        except ValueError: return '#'

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='strict-origin-when-cross-origin'
        response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self'; script-src 'self'; font-src 'self'; img-src 'self' data:; media-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        if request.path.startswith('/admin'): response.headers['Cache-Control']='no-store'
        return response

    @app.get('/')
    def index():
        with database.connect() as c:
            editions=[]
            for kind in ('positive','all'):
                row=c.execute('SELECT * FROM episodes WHERE kind=? ORDER BY day DESC LIMIT 1',(kind,)).fetchone()
                editions.append(episode_view(row) if row else {'kind':kind,'available':False,'status':'pending'})
            updated=c.execute("SELECT value FROM settings WHERE key='last_rss_check'").fetchone()
        return render_template('index.html',editions=editions,last_update=updated[0] if updated else None, **list_articles(request.args))

    @app.get('/archiv')
    def archive(): return render_template('index.html', **list_articles(request.args,archive=True))

    @app.get('/clanok/<article_id>')
    def detail(article_id):
        with database.connect() as c:
            row=c.execute('SELECT a.*,s.name source_name FROM clanky a LEFT JOIN sources s ON s.id=a.source_id WHERE a.id=?',(article_id,)).fetchone()
            if not row: abort(404)
            aliases=[dict(r) for r in c.execute('SELECT al.*,s.name source_name FROM article_aliases al LEFT JOIN sources s ON s.id=al.source_id WHERE article_id=?',(article_id,))]
        return render_template('article.html', item=article(row),aliases=aliases)

    @app.get('/o-projekte')
    def about(): return render_template('about.html')

    @app.get('/podcasty/<episode_id>/kapitoly.json')
    def podcast_chapters(episode_id):
        with database.connect() as c:
            row=c.execute('SELECT * FROM episodes WHERE id=?',(episode_id,)).fetchone()
        if not row: abort(404)
        ep=episode_view(row)
        # Textual chapter metadata survives audio expiry; no synthesis on reads.
        return {'available':ep['available'],'chapters':[{'title':ch.get('title',''),'start':ch.get('start',0)} for ch in ep['chapters'] if isinstance(ch,dict)]}

    @app.get('/podcasty')
    def podcasts():
        with database.connect() as c:
            episodes=[episode_view(r) for r in c.execute('SELECT * FROM episodes ORDER BY day DESC,kind LIMIT 60')]
        return render_template('podcasts.html',episodes=episodes)

    @app.get('/podcasty/<episode_id>')
    def podcast_detail(episode_id):
        with database.connect() as c:
            row=c.execute('SELECT * FROM episodes WHERE id=?',(episode_id,)).fetchone()
            if not row: abort(404)
            episode=episode_view(row); ids=episode['article_ids']
            items=[article(r) for r in c.execute('SELECT * FROM clanky WHERE id IN (' + ','.join('?' for _ in ids) + ')',ids)] if ids else []
        return render_template('podcast.html',episode=episode,articles=items)

    @app.get('/audio/<episode_id>')
    def audio(episode_id):
        with database.connect() as c: row=c.execute('SELECT * FROM episodes WHERE id=?',(episode_id,)).fetchone()
        if not row: abort(404)
        path=live_audio(dict(row))
        if not path: abort(410,description='Audio tejto epizódy už nie je dostupné.')
        try: response=send_file(path,mimetype='audio/mpeg',conditional=True,etag=True)
        except FileNotFoundError: abort(410,description='Audio tejto epizódy už nie je dostupné.')
        expires=parsed_time(row['expires_at'])
        response.headers['Cache-Control']='private, no-store'
        response.headers['Expires']=format_datetime(expires,usegmt=True)
        return response

    @app.get('/static/podcast_<legacy>.mp3')
    def legacy_audio(legacy):
        kind={'pozitivny':'positive','vsetky':'all'}.get(legacy)
        if not kind: abort(410)
        with database.connect() as c: rows=c.execute('SELECT * FROM episodes WHERE kind=? ORDER BY day DESC',(kind,)).fetchall()
        for row in rows:
            if live_audio(dict(row)): return redirect(url_for('audio',episode_id=row['id']),code=302)
        abort(410)

    @app.get('/podcast/<kind>.xml')
    def rss(kind):
        if kind not in ('positive','all'): abort(404)
        title='Pozitívne správy' if kind=='positive' else 'Všetky správy'
        root=ET.Element('rss',version='2.0'); channel=ET.SubElement(root,'channel')
        for name,value in [('title',title),('link',url_for('podcasts',_external=True)),('description','Denný prehľad správ v slovenčine.'),('language','sk')]: ET.SubElement(channel,name).text=value
        with database.connect() as c: rows=c.execute('SELECT * FROM episodes WHERE kind=? ORDER BY day DESC LIMIT 60',(kind,)).fetchall()
        for row in rows:
            ep=dict(row); path=live_audio(ep)
            if not path: continue
            item=ET.SubElement(channel,'item')
            for name,value in [('title',ep['title']),('link',url_for('podcast_detail',episode_id=ep['id'],_external=True)),('description',ep.get('transcript') or ''),('guid',ep['id'])]: ET.SubElement(item,name).text=value
            dt=parsed_time(ep.get('published_at'))
            if dt: ET.SubElement(item,'pubDate').text=format_datetime(dt.astimezone(timezone.utc),usegmt=True)
            ET.SubElement(item,'enclosure',url=url_for('audio',episode_id=ep['id'],_external=True),length=str(path.stat().st_size),type='audio/mpeg')
        return Response(ET.tostring(root,encoding='utf-8',xml_declaration=True),mimetype='application/rss+xml')

    @app.get('/healthz')
    def health(): return {'status':'ok'}

    @app.get('/readyz')
    def ready():
        try:
            with database.connect() as c: c.execute('SELECT 1 FROM clanky LIMIT 1').fetchone()
            return {'status':'ready'}
        except Exception: return {'status':'not_ready'},503

    @app.get('/admin')
    @access_required
    def admin():
        if 'csrf' not in session: session['csrf']=secrets.token_urlsafe(32)
        with database.connect() as c:
            sources=[dict(r) for r in c.execute('SELECT * FROM sources ORDER BY name')]
            tasks=[dict(r) for r in c.execute('SELECT id,kind,state,attempts,error,updated_at FROM tasks ORDER BY updated_at DESC LIMIT 100')]
            counts={r['state']:r['n'] for r in c.execute('SELECT state,count(*) n FROM tasks GROUP BY state')}
            usage=[dict(r) for r in c.execute('SELECT * FROM ai_usage ORDER BY id DESC LIMIT 100')]
            usage_totals=dict(c.execute("SELECT count(*) calls,count(total_tokens) measured_calls,sum(input_tokens) input_tokens,sum(output_tokens) output_tokens,sum(reasoning_tokens) reasoning_tokens,sum(cached_tokens) cached_tokens,sum(total_tokens) total_tokens FROM ai_usage WHERE task IN ('article','long_article')").fetchone())
            usage_totals['articles']=c.execute("SELECT count(*) FROM clanky WHERE analysis_version=?",(config.ANALYSIS_VERSION,)).fetchone()[0]
            usage_totals['tokens_per_article']=(round(usage_totals['total_tokens']/usage_totals['articles']) if usage_totals['articles'] and usage_totals['total_tokens'] is not None else None)
            episodes=[episode_view(r) for r in c.execute('SELECT * FROM episodes ORDER BY day DESC LIMIT 30')]
            runs=[dict(r) for r in c.execute('SELECT * FROM job_runs ORDER BY started_at DESC LIMIT 20')]
        audio_dir=config.AUDIO_DIR
        disk=shutil.disk_usage(audio_dir if audio_dir.exists() else audio_dir.resolve().parent) if audio_dir.resolve().parent.exists() else None
        audio_bytes=sum(p.stat().st_size for p in audio_dir.glob('*.mp3')) if audio_dir.exists() else 0
        return render_template('admin.html',sources=sources,tasks=tasks,counts=counts,usage=usage,episodes=episodes,runs=runs,
                               paused=database.setting('pipeline_paused','0')=='1',csrf=session['csrf'],disk=disk,audio_bytes=audio_bytes,usage_totals=usage_totals)

    @app.post('/admin/action')
    @access_required
    def admin_action():
        token=request.form.get('csrf',''); expected=session.get('csrf','')
        if not token or not expected or not hmac.compare_digest(token,expected): abort(403)
        action=request.form.get('action')
        if action in ('pause','resume'): database.set_setting('pipeline_paused','1' if action=='pause' else '0')
        elif action=='retry':
            target=request.form.get('target',''); target_type=request.form.get('target_type','task')
            with database.connect() as c:
                if target_type=='task':
                    c.execute("UPDATE tasks SET state='pending',attempts=0,error=NULL,lease_until=NULL,available_at=?,updated_at=? WHERE id=? AND state='failed'",(database.utcnow(),database.utcnow(),target))
                elif target_type=='episode':
                    c.execute("UPDATE episodes SET status='pending',attempts=0,available_at=NULL,error=NULL,lease_until=NULL WHERE id=? AND status='failed'",(target,))
                else: abort(400)
        else: abort(400)
        return redirect(url_for('admin'),code=303)

    @app.errorhandler(404)
    @app.errorhandler(403)
    @app.errorhandler(410)
    @app.errorhandler(503)
    def error_page(error): return render_template('error.html',error=error),error.code
    return app

app=create_app()
if __name__=='__main__': app.run(host='0.0.0.0',port=5001)
