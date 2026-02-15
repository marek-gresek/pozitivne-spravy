import feedparser
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
import json
from datetime import datetime, timedelta
import time
import logging
import uuid
from config import GEMINI_API_KEY, RSS_FEEDS
from database import init_db, uloz_clanok, clanok_existuje

# Nastavenie logovania
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("spracovanie.log"),
        logging.StreamHandler()
    ]
)

genai.configure(api_key=GEMINI_API_KEY)

# Inicializácia databázy
init_db()

def stiahni_plny_text(url):
    try:
        response = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        paragraphs = soup.find_all('p')
        full_text = ' '.join([p.get_text() for p in paragraphs])
        return full_text
    except Exception as e:
        logging.error(f"Nepodarilo sa stiahnuť text z {url}: {e}")
        return None

# --- NOVÁ FUNKCIA: PREKLAD V DÁVKACH ---
def preloz_davku_clankov(clanky_na_preklad):
    """Preloží celú dávku článkov (nadpisy a texty) do slovenčiny naraz."""
    if not clanky_na_preklad:
        return []

    prompt_articles = ""
    for clanok in clanky_na_preklad:
        prompt_articles += f"Článok ID: {clanok['id']}\n"
        prompt_articles += f"Nadpis: {clanok['nadpis']}\n"
        prompt_articles += f"Text:\n{clanok['text'][:4000]}\n---\n"
    
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = f"""
        Prelož nasledujúci zoznam článkov do slovenčiny.
        Vráť JSON pole (array), kde každý objekt reprezentuje jeden článok.
        Každý objekt MUSÍ obsahovať tieto tri kľúče:
        1. "id": Pôvodné ID článku.
        2. "prelozeny_nadpis": Preložený nadpis.
        3. "prelozeny_text": Preložený text.
        
        Zoznam na preklad: --- {prompt_articles} ---
        """
        response = model.generate_content(prompt)
        time.sleep(30)  # Krátke čakanie z dovodu limutu RPM na Gemini API
        cleaned_response = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(cleaned_response)
    except Exception as e:
        logging.error(f"CHYBA pri dávkovom preklade: {e}")
        return []

def analyzuj_davku_clankov(clanky_na_analyzu):
    """Spracuje celú dávku slovenských článkov v jednej požiadavke na Gemini API."""
    if not clanky_na_analyzu: return []
    prompt_articles = ""
    for clanok in clanky_na_analyzu:
        prompt_articles += f"Článok ID: {clanok['id']}\nTEXT:\n{clanok['text'][:4000]}\n---\n"
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = f"""
        Analyzuj nasledujúci zoznam článkov v slovenčine.
        Vráť JSON pole (array), kde každý objekt reprezentuje jeden článok.
        Každý objekt MUSÍ obsahovať tieto tri kľúče:
        1. "id": Pôvodné ID článku.
        2. "sentiment": Hodnota "Pozitívny", "Neutrálny" alebo "Negatívny".
        3. "zhrnutie": Krátke zhrnutie článku v slovenčine (max 5 viet).
        Zoznam článkov na analýzu: --- {prompt_articles} ---
        """
        response = model.generate_content(prompt)
        time.sleep(30)  # Krátke čakanie z dovodu limutu RPM na Gemini API
        cleaned_response = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(cleaned_response)
    except Exception as e:
        logging.error(f"Chyba pri dávkovej analýze: {e}")
        return []
        
def main():
    logging.info("Spúšťam plne optimalizované dávkové spracovanie článkov...")
    spracovane_pocet = 0
    hladany_datum = (datetime.now() - timedelta(days=1)).date()
    logging.info(f"Hľadajú sa články z dátumu: {hladany_datum.strftime('%d.%m.%Y')}")

    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"

    for feed_url, feed_info in RSS_FEEDS.items():
        kategoria, jazyk = feed_info['kategoria'], feed_info['jazyk']
        logging.info(f"Spracovávam kanál '{kategoria}' ({jazyk}): {feed_url}")
        
        feed = feedparser.parse(feed_url, agent=USER_AGENT)
        if feed.bozo:
            logging.error(f"Kanál je poškodený. Dôvod: {feed.bozo_exception}")
            continue
        
        # KROK 1: Zozbieraj všetky články z daného dňa
        denne_clanky = []
        for index, entry in enumerate(feed.entries):
            datum_publikovania = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                datum_publikovania = datetime.fromtimestamp(time.mktime(entry.published_parsed)).date()

            # Kontrola (zjednodušená), ak nemáme ID, použijeme link ako ID
            # Poznámka: v novom DB systéme vygenerujeme UUID ak bude treba, alebo použijeme link
            clanok_id_hash = str(uuid.uuid5(uuid.NAMESPACE_URL, entry.link))

            if datum_publikovania == hladany_datum:
                if clanok_existuje(clanok_id_hash):
                    logging.info(f"Článok {entry.title} už existuje v DB, preskakujem.")
                    continue
                
                denne_clanky.append({'id': index, 'db_id': clanok_id_hash, 'entry': entry})

        if not denne_clanky:
            logging.info("Nenašli sa žiadne nové články z požadovaného dňa.")
            continue
        
        logging.info(f"Nájdených {len(denne_clanky)} nových článkov. Sťahujem plné texty...")

        # KROK 2: Stiahni texty a priprav dávky na preklad a analýzu
        pripravene_clanky_na_analyzu = []
        clanky_na_preklad = []
        for clanok in denne_clanky:
            plny_text = stiahni_plny_text(clanok['entry'].link)
            if plny_text:
                clanok_data = {'id': clanok['id'], 'db_id': clanok['db_id'], 'nadpis': clanok['entry'].title, 'text': plny_text, 'original_entry': clanok['entry']}
                if jazyk == 'sk':
                    pripravene_clanky_na_analyzu.append(clanok_data)
                else:
                    clanky_na_preklad.append(clanok_data)

        # KROK 3: Dávkový preklad (ak je potrebný)
        if clanky_na_preklad:
            logging.info(f"Odosielam dávku {len(clanky_na_preklad)} článkov na preklad...")
            prelozene_vysledky = preloz_davku_clankov(clanky_na_preklad)
            logging.info(f"Prijatých {len(prelozene_vysledky)} preložených výsledkov.")
            
            # Priradenie preložených textov k pôvodným článkom
            for vysledok in prelozene_vysledky:
                original = next((c for c in clanky_na_preklad if str(c['id']) == str(vysledok.get('id'))), None)
                if original and vysledok.get('prelozeny_nadpis') and vysledok.get('prelozeny_text'):
                    original['povodny_nadpis'] = original['nadpis'] # Ulozime povodny
                    original['nadpis'] = vysledok['prelozeny_nadpis']
                    original['text'] = vysledok['prelozeny_text']
                    pripravene_clanky_na_analyzu.append(original)

        # KROK 4: Dávková analýza všetkých článkov (už v slovenčine)
        if pripravene_clanky_na_analyzu:
            logging.info(f"Odosielam finálnu dávku {len(pripravene_clanky_na_analyzu)} článkov na analýzu...")
            analyzovane_vysledky = analyzuj_davku_clankov(pripravene_clanky_na_analyzu)
            logging.info(f"Prijatých {len(analyzovane_vysledky)} finálnych výsledkov.")

            for vysledok in analyzovane_vysledky:
                original = next((c for c in pripravene_clanky_na_analyzu if str(c['id']) == str(vysledok.get('id'))), None)
                if original and vysledok.get('sentiment') and vysledok.get('zhrnutie'):
                    clanok_data = {
                        'id': original['db_id'], # Pouzijeme hash ID
                        'nadpis': original['nadpis'],
                        'link': original['original_entry'].link,
                        'zhrnutie': vysledok['zhrnutie'],
                        'datum_publikovania': hladany_datum.strftime('%d.%m.%Y'),
                        'kategoria': kategoria,
                        'sentiment': vysledok['sentiment'],
                        'povodny_nadpis': original.get('povodny_nadpis', ''),
                        'full_text': original.get('text', '') # Ulozime aj full text ak chceme
                    }
                    uloz_clanok(clanok_data)
                    spracovane_pocet += 1
        
    logging.info(f"Hotovo. Celkovo spracovaných a uložených {spracovane_pocet} článkov.")

if __name__ == "__main__":
    main()
