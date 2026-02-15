import sqlite3
import os
from datetime import datetime

DB_FILE = 'clanky.db'

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row  # To return dict-like objects
    return conn

def init_db():
    conn = get_db_connection()
    with conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS clanky (
                id TEXT PRIMARY KEY,
                nadpis TEXT NOT NULL,
                link TEXT NOT NULL,
                zhrnutie TEXT,
                sentiment TEXT,
                kategoria TEXT,
                datum_publikovania TEXT,
                povodny_nadpis TEXT,
                full_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    conn.close()

def uloz_clanok(clanok):
    conn = get_db_connection()
    try:
        with conn:
            conn.execute('''
                INSERT OR REPLACE INTO clanky (id, nadpis, link, zhrnutie, sentiment, kategoria, datum_publikovania, povodny_nadpis, full_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                clanok['id'],
                clanok['nadpis'],
                clanok['link'],
                clanok.get('zhrnutie', ''),
                clanok.get('sentiment', 'Neznámy'),
                clanok.get('kategoria', 'Neznáma'),
                clanok.get('datum_publikovania', ''),
                clanok.get('povodny_nadpis', ''),
                clanok.get('full_text', '')
            ))
    finally:
        conn.close()

def nacitaj_vsetky_clanky():
    conn = get_db_connection()
    clanky = conn.execute('SELECT * FROM clanky ORDER BY created_at DESC').fetchall()
    conn.close()
    return [dict(clanok) for clanok in clanky]

def clanok_existuje(clanok_id):
    conn = get_db_connection()
    clanok = conn.execute('SELECT id FROM clanky WHERE id = ?', (clanok_id,)).fetchone()
    conn.close()
    return clanok is not None
