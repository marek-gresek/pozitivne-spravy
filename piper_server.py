"""Private fixed-voice Piper service; single inference thread, bounded requests."""
import io
import json
import threading
import wave
from pathlib import Path
from flask import Flask, Response, abort, request
import onnxruntime
from piper import PiperVoice
from piper.config import PiperConfig

model=Path('/voices/sk_SK-lili-medium.onnx')
options=onnxruntime.SessionOptions()
options.intra_op_num_threads=1
options.inter_op_num_threads=1
voice=PiperVoice(session=onnxruntime.InferenceSession(str(model),sess_options=options,providers=['CPUExecutionProvider']),
                 config=PiperConfig.from_dict(json.loads(Path(str(model)+'.json').read_text())))
lock=threading.Lock()
app=Flask(__name__)
app.config['MAX_CONTENT_LENGTH']=16000

@app.get('/healthz')
def health():return {'status':'ok','voice':'sk_SK-lili-medium'}

@app.post('/synthesize')
def synthesize():
    data=request.get_json(silent=True) or {}
    if not isinstance(data,dict):abort(400)
    text=data.get('text')
    if data.get('voice','sk_SK-lili-medium')!='sk_SK-lili-medium' or not isinstance(text,str) or not 1<=len(text.strip())<=1800:abort(400)
    with lock,io.BytesIO() as output:
        with wave.open(output,'wb') as wav:voice.synthesize_wav(text.strip(),wav)
        return Response(output.getvalue(),mimetype='audio/wav')

if __name__=='__main__':app.run(host='0.0.0.0',port=5000,threaded=False)
