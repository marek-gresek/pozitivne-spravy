#!/bin/bash
# Tento skript spúšťa celý proces spracovania: stiahnutie správ, vytvorenie skriptov a generovanie podcastov.

# Presmerovanie výstupu do logu (pre istotu, ak by cron zlyhal s presmerovaním)
exec >> /var/log/cron.log 2>&1

echo "----------------------------------------"
echo "Spúšťam denné spracovanie: $(date)"

# 1. Stiahnutie a spracovanie článkov (uloženie do DB)
echo "Krok 1: Sťahovanie a analýza článkov..."
/usr/local/bin/python /app/spracuj_clanky.py

# 2. Vytvorenie textových skriptov pre podcasty
echo "Krok 2: Generovanie scenárov pre podcasty..."
/usr/local/bin/python /app/script_podcast.py

# 3. Vygenerovanie audio súborov (MP3)
echo "Krok 3: Generovanie audio podcastov..."
/usr/local/bin/python /app/vytvor_podcasty.py

echo "Spracovanie dokončené: $(date)"
echo "----------------------------------------"
