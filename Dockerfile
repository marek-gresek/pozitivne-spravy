# Krok 1: Použi oficiálny Python image pre ARM architektúru (Raspberry Pi)
FROM python:3.11-slim

# Nastavenie pracovného adresára
WORKDIR /app

# Inštalácia systémových závislostí (cron pre plánovanie)
RUN apt-get update && apt-get install -y --no-install-recommends \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Krok 3: Skopíruj súbor s knižnicami a nainštaluj ich
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Krok 4: Skopíruj zvyšok aplikácie do pracovného priečinka
COPY . .

# Vytvorenie cron jobu (podľa tvojho nastavenia o 9:00 ráno)
RUN echo "0 9 * * * /bin/bash /app/run_tasks.sh" > /etc/cron.d/spracovanie-cron
RUN chmod 0644 /etc/cron.d/spracovanie-cron
# Pridáme práva na spustenie pre náš nový skript
RUN chmod +x /app/run_tasks.sh
RUN crontab /etc/cron.d/spracovanie-cron

# Vytvorenie prázdneho logu pre cron
RUN touch /var/log/cron.log

# Krok 5: Povedz Dockeru, že naša aplikácia bude bežať na porte 5001
EXPOSE 5001

# Krok 6: Príkaz, ktorý sa spustí pri štarte kontajnera
CMD ["gunicorn", "--workers", "3", "--bind", "0.0.0.0:5001", "app:app"]

