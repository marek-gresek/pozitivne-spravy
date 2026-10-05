"""Private fixed Supertonic 3 M1 voice, offline CPU inference and bounded requests."""
import io
import threading
import wave
import numpy as np
from flask import Flask, Response, abort, request
from supertonic import TTS

VOICE = 'M1'
MAX_CHARS = 600
SPEECH_SPEED = 1.15


def shorten_long_pauses(samples, sample_rate):
    """Keep speech and short pauses; shorten near-silent runs over 0.9 s to 0.4 s.

    Twenty-millisecond RMS frames avoid treating individual waveform zeroes as
    pauses. Keep both edges of every run so quiet word endings stay intact.
    """
    frame_size = max(1, round(sample_rate * 0.02))
    count = samples.size // frame_size
    if not count:
        return samples
    frames = samples[:count * frame_size].reshape(count, frame_size)
    quiet = np.mean(np.square(frames), axis=1) < 10 ** (-55 / 10)
    edges = np.flatnonzero(np.diff(np.r_[False, quiet, False]))
    keep_edge = round(sample_rate * 0.2)
    parts = []
    cursor = 0
    for first, last in zip(edges[::2], edges[1::2]):
        start, end = int(first) * frame_size, int(last) * frame_size
        if end - start <= sample_rate * 0.9:
            continue
        parts.append(samples[cursor:start + keep_edge])
        cursor = end - keep_edge
    if not parts:
        return samples
    parts.append(samples[cursor:])
    return np.concatenate(parts)


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
        # Keep the approved voice; control pace during synthesis, not playback.
        np.random.seed(42)
        samples, _ = engine.synthesize(text.strip(), voice_style=style, lang='sk',
                                       total_steps=16, speed=SPEECH_SPEED, silence_duration=0.2)
        samples = np.asarray(samples).reshape(-1)
        if not samples.size or not np.all(np.isfinite(samples)):
            abort(502)
        samples = shorten_long_pauses(samples, engine.sample_rate)
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
