# Súbor: app.py
from flask import Flask, render_template
import os
from datetime import datetime
from collections import OrderedDict
from config import RSS_FEEDS
from database import nacitaj_vsetky_clanky

app = Flask(__name__)

@app.context_processor
def inject_now():
    return {'now': datetime.utcnow}

@app.route('/')
def index():
    clanky = nacitaj_vsetky_clanky()
    
    # --- NOVÁ LOGIKA PRE ŠTATISTIKY ---
    stats = {'total': 0, 'pozitivne': {'count': 0, 'percent': 0}, 'neutralne': {'count': 0, 'percent': 0}, 'negativne': {'count': 0, 'percent': 0}}
    stats['total'] = len(clanky)

    if stats['total'] > 0:
        for clanok in clanky:
            sentiment = clanok.get('sentiment', 'Neznámy').lower()
            if sentiment == 'pozitívny':
                stats['pozitivne']['count'] += 1
            elif sentiment == 'neutrálny':
                stats['neutralne']['count'] += 1
            elif sentiment == 'negatívny':
                stats['negativne']['count'] += 1
        
        # Výpočet percent
        stats['pozitivne']['percent'] = round((stats['pozitivne']['count'] / stats['total']) * 100, 1)
        stats['neutralne']['percent'] = round((stats['neutralne']['count'] / stats['total']) * 100, 1)
        stats['negativne']['percent'] = round((stats['negativne']['count'] / stats['total']) * 100, 1)
    # --- KONIEC NOVEJ LOGIKY ---

    kategorie = OrderedDict()
    for clanok in clanky:
        kategoria = clanok.get('kategoria', 'Nezaradené')
        if kategoria not in kategorie:
            kategorie[kategoria] = []
        kategorie[kategoria].append(clanok)
        
    # --- NOVÁ LOGIKA PRE PODCASTY ---
    podcast_pozitivny_exists = os.path.exists('static/podcast_pozitivny.mp3')
    podcast_vsetky_exists = os.path.exists('static/podcast_vsetky.mp3')
    
    # Do šablóny posielame aj nové dáta 'stats'
    return render_template(
        'index.html', 
        kategorie=kategorie, 
        zdroje=RSS_FEEDS, 
        stats=stats,
        podcast_pozitivny_exists=podcast_pozitivny_exists,
        podcast_vsetky_exists=podcast_vsetky_exists
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)