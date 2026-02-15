#!/bin/bash

# Krok 1: Okamžite presmeruj všetok budúci výstup (štandardný aj chybový) do log súboru.
# Toto je najdôležitejšia časť pre spoľahlivý logging v crone.
exec >> /home/marek/positivne_spravy/cron.log 2>&1

# Krok 2: Pre istotu manuálne nastavíme premennú PATH, aby cron našiel všetky príkazy.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# --- Štart Diagnostiky ---
echo "----------------------------------------"
echo "Automatická aktualizácia spustená: $(date)"
echo "DEBUG: Skript beží pod používateľom: $(whoami)"

# Krok 3: Bezpečne prejdeme do priečinka, kde sa nachádza tento skript.
cd "$(dirname "$0")"
echo "DEBUG: Pracovný priečok je teraz: $(pwd)"

# --- Spustenie samotných úloh ---
echo "Spúšťam spracuj_clanky.py..."
/usr/bin/docker exec pozitivne-spravy-app python /app/spracuj_clanky.py

echo "Spúšťam script_podcast.py..."
/usr/bin/docker exec pozitivne-spravy-app python /app/script_podcast.py

echo "Spúšťam vytvor_podcasty.py..."
/usr/bin/docker exec pozitivne-spravy-app python /app/vytvor_podcasty.py

echo "Aktualizácia dokončená: $(date)"
echo "----------------------------------------"
