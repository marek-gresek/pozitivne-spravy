import os
from config import GEMINI_PODCAST_API_KEY
from google import genai
from google.genai import types
import wave
import time

# --- Konfigurácia ---
POSITIVE_SCRIPT_FILE = 'script_pozitivny.txt'
ALL_SCRIPT_FILE = 'script_vsetky.txt'
OUTPUT_DIR = 'static'
POSITIVE_PODCAST_FILE = os.path.join(OUTPUT_DIR, 'podcast_pozitivny.mp3')
ALL_PODCAST_FILE = os.path.join(OUTPUT_DIR, 'podcast_vsetky.mp3')

# Konfigurácia pre oba štýly API
client = genai.Client(api_key=GEMINI_PODCAST_API_KEY)

def vytvorit_mp3_subor(filename, pcm, channels=1, rate=24000, sample_width=2):
   with wave.open(filename, "wb") as wf:
      wf.setnchannels(channels)
      wf.setsampwidth(sample_width)
      wf.setframerate(rate)
      wf.writeframes(pcm)

def preved_text_na_rec(text, vystupny_subor_mp3):
    """Prevedie text na reč a priamo ho uloží ako MP3 súbor."""
    if not text: 
        return False
    print(f"-> Získavam audio stream a ukladám do {vystupny_subor_mp3}...")
    
    try:
        # Získanie audio dát z API
        response = client.models.generate_content(
            model="gemini-2.5-flash-preview-tts",
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name='Achird',
                        )
                    )
                ),
            )
        )
        audio_data = response.candidates[0].content.parts[0].inline_data.data
        
        # Priame uloženie MP3 dát do súboru
        vytvorit_mp3_subor(vystupny_subor_mp3, audio_data)
        
        print(f"-> Podcast úspešne uložený ako {vystupny_subor_mp3}.")
        time.sleep(30)  # Krátke čakanie z dovodu limitu RPM na Gemini API
        return True
    except Exception as e:
        print(f"  -> Chyba pri prevode textu na reč: {e}")
        return False

def main():
    print("Spúšťam generovanie audio súborov podcastov...")
    
    if os.path.exists(POSITIVE_SCRIPT_FILE):
        print("\n--- Generujem podcast z pozitívnych správ ---")
        with open(POSITIVE_SCRIPT_FILE, 'r', encoding='utf-8') as f:
            script_text = f.read()
        preved_text_na_rec(script_text, POSITIVE_PODCAST_FILE)
    else:
        print("\n-> Súbor so skriptom pre pozitívne správy nebol nájdený.")

    if os.path.exists(ALL_SCRIPT_FILE):
        print("\n--- Generujem podcast zo všetkých správ ---")
        with open(ALL_SCRIPT_FILE, 'r', encoding='utf-8') as f:
            script_text = f.read()
        preved_text_na_rec(script_text, ALL_PODCAST_FILE)
    else:
        print("\n-> Súbor so skriptom pre všetky správy nebol nájdený.")
        
    print("\nGenerovanie podcastov dokončené.")

if __name__ == "__main__":
    main()