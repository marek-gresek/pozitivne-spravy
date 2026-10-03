"""Text-only streaming Responses adapter. Never logs secrets, prompts or raw errors."""
import json
import time
import uuid
from pathlib import Path
import requests
from config import AI_ENDPOINT, ALLOWED_MODELS, KEY_FILE, USER_AGENT, AI_TEXT_PROFILE
from database import connect, utcnow

class AIError(Exception):
    def __init__(self, code, transient=False, quota=False):
        super().__init__(code); self.code=code; self.transient=transient; self.quota=quota

class ResponsesClient:
    def __init__(self, key_file=KEY_FILE, session=None):
        self.key_file=key_file; self.session=session or requests.Session()

    def generate(self, model, instructions, prompt, task='article'):
        if model not in ALLOWED_MODELS: raise ValueError('model_not_allowed')
        started=time.monotonic(); usage={}; request_id=None; status='failed'
        try:
            key=Path(self.key_file).read_text().strip()
            with self.session.post(AI_ENDPOINT,headers={'Authorization':'Bearer '+key,
                'User-Agent':USER_AGENT,'Content-Type':'application/json'},json={'model':model,
                'stream':True,'reasoning':{'effort':'high'},'instructions':instructions,'input':prompt,
                'tools':[],**({'metadata':{'text_profile':AI_TEXT_PROFILE}} if AI_TEXT_PROFILE else {})},stream=True,timeout=(20,300)) as response:
                request_id=response.headers.get('x-request-id')
                if response.status_code>=400:
                    # Public bot rejection, auth and contract errors are not quota exhaustion.
                    raise AIError('http_'+str(response.status_code),transient=response.status_code>=500 or response.status_code==429,
                                  quota=response.status_code==429)
                chunks=[]; final=None; event_lines=[]; received=0
                response.encoding='utf-8'
                for line in response.iter_lines(decode_unicode=True):
                    if line is None: continue
                    if isinstance(line,bytes): line=line.decode('utf-8')
                    if line.startswith('data:'): event_lines.append(line[5:].strip())
                    elif line=='':
                        if not event_lines: continue
                        raw='\n'.join(event_lines); event_lines=[]
                        if raw=='[DONE]': continue
                        try: event=json.loads(raw)
                        except json.JSONDecodeError: raise AIError('invalid_sse')
                        typ=event.get('type','')
                        if typ=='response.output_text.delta':
                            delta=event.get('delta',''); received+=len(delta.encode('utf-8'))
                            if received>256_000: raise AIError('output_too_large')
                            chunks.append(delta)
                        elif typ=='response.completed':
                            final=event.get('response',{}); request_id=final.get('id',request_id)
                            usage=final.get('usage') or {}
                        elif typ in ('response.failed','response.incomplete','error','response.error'):
                            code=(event.get('error') or event.get('response',{}).get('error') or {}).get('code','response_failed')
                            raise AIError('response_failed',transient=True,quota='quota' in str(code) or 'rate_limit' in str(code))
                if final is None or final.get('status','completed')!='completed': raise AIError('incomplete_stream',transient=True)
                text=''.join(chunks)
                if not text:
                    text=''.join(p.get('text','') for item in final.get('output',[]) if item.get('type')=='message' for p in item.get('content',[]) if p.get('type')=='output_text')
                if not text: raise AIError('empty_output')
                if len(text.encode('utf-8'))>256_000: raise AIError('output_too_large')
                status='success'; return text
        except requests.RequestException:
            raise AIError('network_error',transient=True) from None
        finally:
            details=usage.get('output_tokens_details') or {}; inp=usage.get('input_tokens_details') or {}
            with connect() as c:
                c.execute('''INSERT INTO ai_usage(request_id,model,task,status,duration_ms,input_tokens,output_tokens,
                    reasoning_tokens,cached_tokens,total_tokens,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                    (request_id,model,task,status,int((time.monotonic()-started)*1000),usage.get('input_tokens'),
                     usage.get('output_tokens'),details.get('reasoning_tokens'),inp.get('cached_tokens'),usage.get('total_tokens'),utcnow()))

def json_result(text):
    text=text.strip()
    if text.startswith('```'):
        lines=text.splitlines(); text='\n'.join(lines[1:-1])
    return json.loads(text)
