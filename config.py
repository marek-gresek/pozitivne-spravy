import os

# Načítanie API kľúčov z premenných prostredia (Environment Variables)
# Ak premenná nie je nastavená, použije sa prázdny reťazec alebo vyhodí chybu (podľa potreby)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_PODCAST_API_KEY = os.getenv("GEMINI_PODCAST_API_KEY", "")

if not GEMINI_API_KEY:
    print("VAROVANIE: GEMINI_API_KEY nie je nastavený! Skontrolujte .env súbor.")

RSS_FEEDS = {
    # Slovenské (sk)
    'https://www.sme.sk/rss-title': {'kategoria': 'Slovensko', 'jazyk': 'sk'},
    'https://dennikn.sk/rss/': {'kategoria': 'Slovensko', 'jazyk': 'sk'},
    'https://www.aktuality.sk/rss/': {'kategoria': 'Slovensko', 'jazyk': 'sk'},
    'https://spravy.pravda.sk/rss/xml/': {'kategoria': 'Slovensko', 'jazyk': 'sk'},
    'https://www.teraz.sk/rss/slovensko.rss': {'kategoria': 'Slovensko', 'jazyk': 'sk'},
    'https://www.etrend.sk/rss.html': {'kategoria': 'Ekonomika', 'jazyk': 'sk'},
    'https://www.teraz.sk/rss/ekonomika.rss': {'kategoria': 'Ekonomika', 'jazyk': 'sk'},
    'https://spravy.pravda.sk/regiony/rss/xml/': {'kategoria': 'Regióny', 'jazyk': 'sk'},
    'https://www.teraz.sk/rss/regiony.rss': {'kategoria': 'Regióny', 'jazyk': 'sk'},
    'https://www.zilinak.sk/rss': {'kategoria': 'Regióny', 'jazyk': 'sk'},
    'https://kultura.pravda.sk/rss/xml/': {'kategoria': 'Kultúra', 'jazyk': 'sk'},
    'https://www.teraz.sk/rss/kultura.rss': {'kategoria': 'Kultúra', 'jazyk': 'sk'},
    'https://www.teraz.sk/rss/magazin.rss': {'kategoria': 'Magazín', 'jazyk': 'sk'},
    'https://zive.aktuality.sk/rss/najnovsie/': {'kategoria': 'Tech & Veda', 'jazyk': 'sk'},
    'https://www.teraz.sk/rss/knihy.rss': {'kategoria': 'Knihy', 'jazyk': 'sk'},
    'https://www.teraz.sk/rss/zdravie.rss': {'kategoria': 'Zdravie', 'jazyk': 'sk'},

    # Anglické (en) - budú automaticky preložené
    'https://feeds.bbci.co.uk/news/world/rss.xml': {'kategoria': 'Svet', 'jazyk': 'en'},
    'https://www.goodnewsnetwork.org/feed/': {'kategoria': 'Svet', 'jazyk': 'en'},
    'https://www.positive.news/feed/': {'kategoria': 'Svet', 'jazyk': 'en'},
    'https://www.goodnewsnetwork.org/category/news/feed/': {'kategoria': 'Svet', 'jazyk': 'en'},
    'https://www.optimistdaily.com/feed/': {'kategoria': 'Svet', 'jazyk': 'en'},
    'https://www.goodgoodgood.co/articles/rss.xml': {'kategoria': 'Svet', 'jazyk': 'en'},
    'https://reasonstobecheerful.world/feed/': {'kategoria': 'Svet', 'jazyk': 'en'},

    # České (cs) - budú automaticky preložené
    'https://servis.idnes.cz/rss.aspx?c=zpravodaj': {'kategoria': 'Svet', 'jazyk': 'cs'},
}
