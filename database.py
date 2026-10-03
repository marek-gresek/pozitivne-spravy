"""Single SQLite source of truth; additive migration preserves the legacy archive."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_FILE = os.getenv('DB_FILE', 'clanky.db')

class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try: return super().__exit__(*args)
        finally: self.close()

def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def get_db_connection():
    conn = sqlite3.connect(DB_FILE, timeout=30, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=30000')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn

connect = get_db_connection

def init_db():
    Path(DB_FILE).resolve().parent.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('''CREATE TABLE IF NOT EXISTS clanky (
            id TEXT PRIMARY KEY,nadpis TEXT NOT NULL,link TEXT NOT NULL,zhrnutie TEXT,
            sentiment TEXT,kategoria TEXT,datum_publikovania TEXT,povodny_nadpis TEXT,
            full_text TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        columns = {r['name'] for r in c.execute('PRAGMA table_info(clanky)')}
        additions = {'canonical_url':'TEXT','content_hash':'TEXT','source_id':'TEXT','language':'TEXT',
            'published_at':'TEXT','topic':'TEXT','region':'TEXT','tags':'TEXT DEFAULT \'[]\'',
            'entities':'TEXT DEFAULT \'[]\'','sentiment_reason':'TEXT','source_scope':'TEXT',
            'analysis_model':'TEXT','analysis_version':'TEXT','updated_at':'TEXT'}
        for name, typ in additions.items():
            if name not in columns: c.execute(f'ALTER TABLE clanky ADD COLUMN {name} {typ}')
        for r in c.execute('SELECT id,datum_publikovania,created_at FROM clanky WHERE published_at IS NULL').fetchall():
            try:
                # Legacy date records have no reliable time; preserve their calendar date.
                d = datetime.strptime(r['datum_publikovania'], '%d.%m.%Y').date()
                from zoneinfo import ZoneInfo
                dt = datetime.combine(d, datetime.min.time(), ZoneInfo('Europe/Prague')).astimezone(timezone.utc)
            except (ValueError, TypeError):
                try: dt = datetime.fromisoformat(r['created_at']).replace(tzinfo=timezone.utc)
                except (ValueError, TypeError): continue
            c.execute('UPDATE clanky SET published_at=? WHERE id=?', (dt.isoformat(timespec='seconds'),r['id']))
        c.executescript('''
        CREATE INDEX IF NOT EXISTS article_date ON clanky(published_at DESC);
        CREATE INDEX IF NOT EXISTS article_hash ON clanky(content_hash);
        CREATE INDEX IF NOT EXISTS article_url ON clanky(canonical_url);
        CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,url TEXT UNIQUE NOT NULL,name TEXT NOT NULL,
            category TEXT,language TEXT,etag TEXT,last_modified TEXT,last_check TEXT,last_success TEXT,error TEXT);
        CREATE TABLE IF NOT EXISTS article_aliases(article_id TEXT REFERENCES clanky(id),source_id TEXT,url TEXT UNIQUE,title TEXT);
        CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,kind TEXT NOT NULL DEFAULT 'article',payload TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
            available_at TEXT,lease_until TEXT,error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS task_queue ON tasks(state,available_at);
        CREATE TABLE IF NOT EXISTS analysis_cache(content_hash TEXT,model TEXT,version TEXT,result TEXT NOT NULL,
            created_at TEXT NOT NULL,PRIMARY KEY(content_hash,model,version));
        CREATE TABLE IF NOT EXISTS ai_usage(id INTEGER PRIMARY KEY,request_id TEXT,model TEXT,task TEXT,status TEXT,
            duration_ms INTEGER,input_tokens INTEGER,output_tokens INTEGER,reasoning_tokens INTEGER,
            cached_tokens INTEGER,total_tokens INTEGER,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS episodes(id TEXT PRIMARY KEY,kind TEXT NOT NULL,day TEXT NOT NULL,title TEXT NOT NULL,
            transcript TEXT,chapters TEXT DEFAULT '[]',article_ids TEXT DEFAULT '[]',status TEXT NOT NULL DEFAULT 'pending',
            audio_file TEXT,duration REAL,published_at TEXT,expires_at TEXT,error TEXT,deleted_at TEXT,
            removed_bytes INTEGER DEFAULT 0,lease_until TEXT,created_at TEXT NOT NULL,UNIQUE(kind,day));
        CREATE TABLE IF NOT EXISTS editorial_reservations(task_id TEXT PRIMARY KEY REFERENCES tasks(id),day TEXT NOT NULL,publisher TEXT NOT NULL,bucket TEXT NOT NULL,score REAL NOT NULL,selected_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS editorial_day ON editorial_reservations(day,publisher);
        CREATE TABLE IF NOT EXISTS editorial_links(candidate_id TEXT PRIMARY KEY REFERENCES tasks(id),representative_id TEXT NOT NULL REFERENCES tasks(id),created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS podcast_days(day TEXT PRIMARY KEY,status TEXT NOT NULL DEFAULT 'waiting',
            created_at TEXT NOT NULL,completed_at TEXT);
        CREATE TABLE IF NOT EXISTS job_runs(id TEXT PRIMARY KEY,kind TEXT,window TEXT,status TEXT,
            started_at TEXT,finished_at TEXT,error TEXT);
        CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(id UNINDEXED,nadpis,zhrnutie,tags);
        CREATE TRIGGER IF NOT EXISTS article_fts_insert AFTER INSERT ON clanky BEGIN
            INSERT INTO articles_fts(id,nadpis,zhrnutie,tags) VALUES(new.id,new.nadpis,new.zhrnutie,new.tags);
        END;
        CREATE TRIGGER IF NOT EXISTS article_fts_update AFTER UPDATE OF nadpis,zhrnutie,tags ON clanky BEGIN
            DELETE FROM articles_fts WHERE id=old.id;
            INSERT INTO articles_fts(id,nadpis,zhrnutie,tags) VALUES(new.id,new.nadpis,new.zhrnutie,new.tags);
        END;
        CREATE TRIGGER IF NOT EXISTS article_fts_delete AFTER DELETE ON clanky BEGIN
            DELETE FROM articles_fts WHERE id=old.id;
        END;
        ''')
        if 'lease_until' not in {r['name'] for r in c.execute('PRAGMA table_info(episodes)')}:
            c.execute('ALTER TABLE episodes ADD COLUMN lease_until TEXT')
        columns={r['name'] for r in c.execute('PRAGMA table_info(episodes)')}
        for name,declaration in [('attempts','INTEGER NOT NULL DEFAULT 0'),('available_at','TEXT')]:
            if name not in columns:c.execute(f'ALTER TABLE episodes ADD COLUMN {name} {declaration}')
        if not c.execute('SELECT 1 FROM settings WHERE key=?',('fts_migrated',)).fetchone():
            c.execute('DELETE FROM articles_fts')
            c.execute('INSERT INTO articles_fts(id,nadpis,zhrnutie,tags) SELECT id,nadpis,zhrnutie,tags FROM clanky')
            c.execute("INSERT INTO settings VALUES('fts_migrated','1')")

def setting(key, default=None):
    with connect() as c:
        r=c.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
    return r['value'] if r else default

def set_setting(key,value):
    with connect() as c: c.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value)))

def nacitaj_vsetky_clanky():
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM clanky WHERE datetime(published_at)>=datetime('now','-2 days') ORDER BY published_at DESC")]

def clanok_existuje(article_id):
    with connect() as c: return c.execute('SELECT 1 FROM clanky WHERE id=?',(article_id,)).fetchone() is not None
