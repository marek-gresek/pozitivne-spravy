# 📰 Správy Dňa (Pozitívne Správy)

![Status](https://img.shields.io/badge/Status-Stable-success)
![License](https://img.shields.io/badge/License-MIT-blue)
![Backend](https://img.shields.io/badge/Backend-Python%20%7C%20Flask-yellow)
![Frontend](https://img.shields.io/badge/Frontend-Bootstrap%205-purple)
![AI](https://img.shields.io/badge/AI-Google%20Gemini-orange)

> **Automatizovaný zberateľ správ, ktorý pomocou umelej inteligencie hľadá pozitivitu v mori informácií a mení články na každodenný podcast.**

## 📖 O Projekte

Tento projekt vznikol s cieľom filtrovať informačný šum a prinášať vyvážený prehľad správ. Automaticky sťahuje články z rôznych RSS kanálov (slovenské, české, anglické), pomocou **Google Gemini AI** ich prekladá do slovenčiny, analyzuje ich sentiment (pozitívny/neutrálny/negatívny) a vytvára stručné zhrnutia.

Čerešničkou na torte je **generovanie vlastného denného podcastu**. AI moderátor vám každé ráno prečíta prehľad toho najdôležitejšieho (alebo len toho pozitívneho), takže nemusíte tráviť hodiny scrollovaním. Celé riešenie je zabalené v Dockeri a optimalizované pre beh na nízko-nákladovom hardvéri ako **Raspberry Pi**.

## ✨ Kľúčové Funkcie

*   **🌍 Multi-jazyčný Zber:** Sťahuje správy zo SK, CZ a EN zdrojov a automaticky ich prekladá do slovenčiny.
*   **🧠 AI Analýza Sentimentu:** Každý článok je vyhodnotený umelou inteligenciou, či je pozitívny, neutrálny alebo negatívny. 😊
*   **🎙️ Generovanie Podcastov:** Automatická tvorba MP3 podcastov s prirodzeným hlasom (Text-to-Speech) – osobitne pre pozitívne správy a pre všeobecný prehľad. 🎧
*   **📊 Interaktívny Dashboard:** Moderné webové rozhranie (Bootstrap 5) s grafmi, filtrami a Dark Mode režimom. 🌒
*   **⚡ Optimalizovaný Výkon:** Lokálna SQLite databáza, logovanie a efektívne využívanie API kvót.
*   **🐳 Docker & Automatizácia:** Plne kontajnerizované riešenie s automatickým spúšťaním úloh (Cron).

## 🛠️ Technologický Zásobník (Tech Stack)

### Backend
*   **Jazyk:** [Python 3.11](https://www.python.org/)
*   **Framework:** [Flask](https://flask.palletsprojects.com/) (ľahký webový server)
*   **Server:** Gunicorn (produkčný WSGI server)
*   **Databáza:** SQLite (rýchla, súborová databáza bez nutnosti konfigurácie)
*   **AI Engine:** [Google Gemini API](https://ai.google.dev/) (modely `gemini-2.5-flash` pre text a `gemini-tts` pre audio)
*   **Plánovanie:** Cron (Linux task scheduler)

### Frontend
*   **Framework:** [Bootstrap 5.3](https://getbootstrap.com/) (Responzívny dizajn)
*   **Templating:** Jinja2 (Flask šablóny)
*   **Ikony:** Bootstrap Icons
*   **Štýl:** Custom CSS s prvkami Glassmorphismu a animáciami

### DevOps & Deployment
*   **Kontajnerizácia:** Docker & Docker Compose
*   **Platforma:** Raspberry Pi / Ubuntu Server / macOS

## 🚀 Spustenie projektu lokálne (Getting Started)

### Predpoklady
*   Python 3.11+
*   Git
*   [Google Gemini API Key](https://aistudio.google.com/app/apikey) (Zadarmo)

### 1. Klonovanie repozitára
```bash
git clone https://github.com/marek-gresek/pozitivne-spravy.git
cd pozitivne-spravy
```

### 2. Nastavenie prostredia
Vytvorte súbor `.env` podľa vzoru `.env.example`:
```bash
cp .env.example .env
```
Otvorte súbor `.env` a vložte svoje API kľúče:
```env
GEMINI_API_KEY=vys_tajny_kluc_z_google_ai_studio
GEMINI_PODCAST_API_KEY=tvoj_tajny_kluc_z_google_ai_studio
```

### 3. Inštalácia a spustenie (bez Dockeru)
```bash
# Vytvorenie virtuálneho prostredia
python -m venv .venv
source .venv/bin/activate  # Na Windows: .venv\Scripts\activate

# Inštalácia závislostí
pip install -r requirements.txt

# Spustenie prvotného spracovania (stiahnutie správ)
python spracuj_clanky.py

# Spustenie webového servera
python app.py
```
Aplikácia pobeží na: `http://localhost:5001`

## 🐳 Nasadenie pomocou Dockeru (Odporúčané)

Toto je preferovaný spôsob pre produkciu a Raspberry Pi.

1.  Uistite sa, že máte vyplnený súbor `.env`.
2.  Spustite kontajnery:
```bash
docker-compose up -d --build
```
3.  Webová aplikácia bude dostupná na `http://localhost:5001`.
4.  Proces sťahovania správ a generovania podcastov sa spustí automaticky podľa plánu (predvolene 09:00 ráno), alebo ho môžete vynútiť reštartom kontajnera `scheduler`.

## 📂 Štruktúra Projektu

```
pozitivne-spravy/
├── app.py                 # Hlavná Flask aplikácia (Web)
├── spracuj_clanky.py      # Skript na sťahovanie, preklad a analýzu správ
├── script_podcast.py      # Generovanie textových scenárov pre podcast
├── vytvor_podcasty.py     # Prevod textu na reč (MP3)
├── database.py            # Práca s SQLite databázou
├── config.py              # Konfigurácia a zoznam RSS kanálov
├── run_tasks.sh           # Bash skript spúšťajúci celý proces (pre Cron)
├── clanky.db              # SQLite databáza (vytvorí sa automaticky)
├── requirements.txt       # Zoznam Python knižníc
├── Dockerfile             # Definícia Docker obrazu
├── docker-compose.yml     # Orchestrácia kontajnerov (App + Scheduler)
├── templates/             # HTML šablóny (Jinja2)
│   └── index.html
└── static/                # CSS, obrázky a vygenerované MP3
    ├── style.css
    ├── podcast_pozitivny.mp3
    └── ...
```

## 🤝 Prispievanie (Contributing)

Príspevky sú vítané! Ak máte nápad na vylepšenie, neváhajte otvoriť Issue alebo poslať Pull Request.
1.  Forknite repozitár.
2.  Vytvorte si vlastnú vetvu (`git checkout -b feature/NovyFeature`).
3.  Commitnite zmeny (`git commit -m 'Pridanie novej funkcie'`).
4.  Pushnite do vetvy (`git push origin feature/NovyFeature`).
5.  Otvorte Pull Request.

## 📄 Licencia

Tento projekt je licencovaný pod licenciou **MIT** - pozrite si súbor [LICENSE](LICENSE) pre viac detailov.

## 👤 Autor

**Marek Grešek**
*   GitHub: [marek-gresek](https://github.com/marek-gresek)

---
*Vyrobené s ❤️ a trochou AI*
