"""Private fixed Supertonic 3 M1 voice, offline CPU inference and bounded requests."""
import io
import threading
import wave
import numpy as np
from flask import Flask, Response, abort, request
from supertonic import TTS

VOICE = 'M1'
MAX_CHARS = 600
engine = TTS(model='supertonic-3', model_dir='/voices', auto_download=False,
             intra_op_num_threads=1, inter_op_num_threads=1)
style = engine.get_voice_style(VOICE)
lock = threading.Lock()
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 8000

@app.get('/healthz')
def health():
    return {'status': 'ok', 'model': 'supertonic-3', 'voice': VOICE, 'language': 'sk'}

@app.post('/synthesize')
def synthesize():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400)
    text = data.get('text')
    if data.get('voice', VOICE) != VOICE or not isinstance(text, str) or not 1 <= len(text.strip()) <= MAX_CHARS:
        abort(400)
    with lock:
        # Match the approved sample; no cloud requests, alternate voices or implicit downloads.
        np.random.seed(42)
        samples, _ = engine.synthesize(text.strip(), voice_style=style, lang='sk',
                                       total_steps=16, speed=1.0, silence_duration=0.35)
        samples = np.asarray(samples).reshape(-1)
        if not samples.size or not np.all(np.isfinite(samples)):
            abort(502)
        pcm = (np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes()
        with io.BytesIO() as output:
            with wave.open(output, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(engine.sample_rate)
                wav.writeframes(pcm)
            return Response(output.getvalue(), mimetype='audio/wav')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=False)
