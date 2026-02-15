# Súbor: script_podcast.py
import json
from datetime import datetime
import os
import time
from config import GEMINI_PODCAST_API_KEY
import google.generativeai as genai
from database import nacitaj_vsetky_clanky

# --- Konfigurácia ---
POSITIVE_SCRIPT_FILE = 'script_pozitivny.txt'
ALL_SCRIPT_FILE = 'script_vsetky.txt'

# --- Konfigurácia pre Štýl B ---
genai.configure(api_key=GEMINI_PODCAST_API_KEY)

def nacitaj_spravy(sentiment_filter=None):
    # Načítanie všetkých správ z DB
    vsetky_spravy = nacitaj_vsetky_clanky()
    
    # Filtrovanie podľa sentimentu ak je zadaný
    if not sentiment_filter:
        return vsetky_spravy
    return [s for s in vsetky_spravy if s.get('sentiment', '').lower() == sentiment_filter.lower()]

def vytvor_script_pre_podcast(clanky, nazov_podcastu):
    if not clanky: return None
    print(f"-> Vytváram skript pre '{nazov_podcastu}' z {len(clanky)} článkov...")
    text_clankov = ""
    for clanok in clanky:
        text_clankov += f"Nadpis: {clanok['nadpis']}\nZhrnutie: {clanok['zhrnutie']}\n---\n"
    try:
        den = datetime.now().strftime('%d. %B %Y')
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = f"""
        Priprav skript pre krátky denný spravodajský podcast v slovenčine s názvom "{nazov_podcastu}".
        Máš k dispozícii nasledujúce zhrnutia najnovších správ. Tvojou úlohou je vybrať 10 až 15 najzaujímavejších tém a vytvoriť z nich plynulý, konverzačný text pre jedného moderátora.
        Začni pútavým úvodom (napr. "Pekný deň, vítam vás pri dnešnom prehľade správ, dnes máme "{den}" a novú nálož správ...") a ukonči to rozlúčením.
        Výsledný skript by mal byť súvislý text, pripravený na nahovorenie.
        Správy na spracovanie: --- {text_clankov} ---
        """
        response = model.generate_content(prompt)
        time.sleep(30)  # Krátke čakanie z dovodu limitu RPM na Gemini API
        return response.text
    except Exception as e:
        print(f"  -> Chyba pri generovaní skriptu: {e}")
        return None

def main():
    print("Spúšťam generovanie skriptov pre podcasty...")
    
    # Podcast z pozitívnych správ
    pozitivne_spravy = nacitaj_spravy(sentiment_filter='pozitívny')
    if pozitivne_spravy:
        script_pozitivny = vytvor_script_pre_podcast(pozitivne_spravy, "Pozitívne správy dňa")
        if script_pozitivny:
            with open(POSITIVE_SCRIPT_FILE, 'w', encoding='utf-8') as f:
                f.write(script_pozitivny)
            print(f"-> Skript pre pozitívne správy úspešne uložený do {POSITIVE_SCRIPT_FILE}")
    else:
        print("-> Nenašli sa žiadne pozitívne správy na vytvorenie skriptu.")
    
    # Podcast zo všetkých správ
    vsetky_spravy = nacitaj_spravy()
    if vsetky_spravy:
        script_vsetky = vytvor_script_pre_podcast(vsetky_spravy, "Prehľad správ dňa")
        if script_vsetky:
            with open(ALL_SCRIPT_FILE, 'w', encoding='utf-8') as f:
                f.write(script_vsetky)
            print(f"-> Skript pre všetky správy úspešne uložený do {ALL_SCRIPT_FILE}")
    else:
        print("-> Nenašli sa žiadne správy na vytvorenie skriptu.")
        
    print("\nGenerovanie skriptov dokončené.")

if __name__ == "__main__":
    main()