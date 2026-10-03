import os
from pathlib import Path
AI_ENDPOINT = os.getenv("OPENAI_RESPONSES_URL", "https://api.openai.com/v1/responses")
AI_TEXT_PROFILE = os.getenv("OPENAI_TEXT_PROFILE", "")
ARTICLE_BATCH_SIZE = 16
ARTICLE_INPUT_BYTES = 60_000
ARTICLE_TEXT_BYTES = 12_000
ALLOWED_MODELS = ("gpt-6-luna", "gpt-6.1-sol")
ARTICLE_MODEL = "gpt-6-luna"
EDITOR_MODEL = "gpt-6.1-sol"
ANALYSIS_VERSION = "2.0"
TIMEZONE = "Europe/Prague"
AUDIO_DIR = Path(os.getenv("AUDIO_DIR", "data/audio"))
TEMP_AUDIO_DIR = AUDIO_DIR / "tmp"
AUDIO_RETENTION_DAYS = 14
TTS_URL = os.getenv("TTS_URL", "http://tts:5000")
TTS_VOICE = "M1"
TTS_MAX_CHARS = 600
KEY_FILE = os.getenv("AI_KEY_FILE", "/run/secrets/ai_key")
USER_AGENT = "PozitivneSpravy/2.0"
TOPICS = ["Politika a verejné dianie", "Ekonomika", "Veda a technológie", "Zdravie", "Životné prostredie", "Spoločnosť", "Vzdelávanie", "Kultúra", "Šport", "Ostatné"]
SENTIMENTS = ["Pozitívny", "Neutrálny", "Negatívny"]

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
