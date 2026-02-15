import json
import os
import sys
from database import uloz_clanok, init_db

def migrate_articles(json_file_path):
    if not os.path.exists(json_file_path):
        print(f"Chyba: Súbor {json_file_path} neexistuje.")
        return

    print(f"Načítavam články zo súboru: {json_file_path}")
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            articles = json.load(f)
    except json.JSONDecodeError:
        print("Chyba: Súbor nie je platný JSON.")
        return

    if not isinstance(articles, list):
        print("Chyba: Očakával sa zoznam článkov (list), ale JSON obsahuje iný formát.")
        return

    print(f"Nájdených {len(articles)} článkov. Začínam migráciu do databázy...")
    
    # Uistíme sa, že tabuľka existuje
    init_db()
    
    count = 0
    for article in articles:
        # Mapovanie starých kľúčov na nové, ak je potrebné
        # Predpokladáme, že štruktúra je kompatibilná, ale pridáme bezpečnosť
        try:
            # Vytvorenie slovníka pre uloz_clanok
            clanok_db = {
                'id': article.get('id') or article.get('link'), # Fallback ID
                'nadpis': article.get('nadpis'),
                'link': article.get('link'),
                'zhrnutie': article.get('zhrnutie', ''),
                'sentiment': article.get('sentiment', 'Neznámy'),
                'kategoria': article.get('kategoria', 'Neznáma'),
                'datum_publikovania': article.get('datum_publikovania', ''),
                'povodny_nadpis': article.get('povodny_nadpis', ''),
                'full_text': article.get('full_text', '')
            }
            
            # Validácia povinných polí
            if not clanok_db['id'] or not clanok_db['nadpis'] or not clanok_db['link']:
                print(f"Preskakujem neplatný článok: {article}")
                continue

            uloz_clanok(clanok_db)
            count += 1
            if count % 10 == 0:
                print(f"Spracovaných {count} článkov...")
                
        except Exception as e:
            print(f"Chyba pri migrácii článku {article.get('nadpis', 'Neznámy')}: {e}")

    print(f"Migrácia dokončená. Úspešne importovaných {count} z {len(articles)} článkov.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Použitie: python migrate.py <cesta_k_clanky.json>")
        # Skúsime nájsť clanky.json v aktuálnom priečinku ako default
        if os.path.exists("clanky.json"):
            migrate_articles("clanky.json")
        else:
            sys.exit(1)
    else:
        migrate_articles(sys.argv[1])
