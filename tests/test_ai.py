"""Offline regressions for the Responses SSE boundary and usage accounting."""
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest
import requests
import database
import ai_client


def test_private_responses_url_is_supplied_only_by_environment():
    result = subprocess.run([sys.executable, '-c', 'import config; print(config.AI_ENDPOINT)'],
        env={**os.environ, 'OPENAI_RESPONSES_URL': 'https://api.example.test/v1/responses'},
        capture_output=True, text=True, check=True)
    assert result.stdout.strip() == 'https://api.example.test/v1/responses'


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_FILE', str(tmp_path / 'test.db'))
    database.init_db()


class Response:
    def __init__(self, events=(), status=200):
        self.status_code = status
        self.headers = {'x-request-id': 'req-test'}
        self.events = events
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_lines(self, **kwargs): yield from self.events


class Session:
    def __init__(self, response): self.response = response; self.calls = []
    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if isinstance(self.response, Exception): raise self.response
        return self.response


def sse(event): return ['data: ' + json.dumps(event), '']
def completed(**kwargs): return {'type': 'response.completed', 'response': {'id': 'resp-test', 'status': 'completed', **kwargs}}
def client(tmp_path, response):
    key = tmp_path / 'key'; key.write_text('offline-test-secret')
    session = Session(response)
    return ai_client.ResponsesClient(str(key), session), session


def test_completed_stream_contract_and_usage(tmp_path):
    lines = [': keepalive', 'event: response.output_text.delta'] + sse({'type': 'response.output_text.delta', 'delta': 'Ahoj'})
    lines += sse(completed(usage={'input_tokens': 10, 'output_tokens': 20, 'total_tokens': 30, 'output_tokens_details': {'reasoning_tokens': 8}, 'input_tokens_details': {'cached_tokens': 5}}))
    obj, session = client(tmp_path, Response(lines))
    assert obj.generate('gpt-6-luna', 'rules', 'source') == 'Ahoj'
    args, kwargs = session.calls[0]
    assert args[0] == 'https://api.openai.com/v1/responses'
    assert kwargs['json'] == {'model': 'gpt-6-luna', 'stream': True, 'reasoning': {'effort': 'high'}, 'instructions': 'rules', 'input': 'source', 'tools': []}
    with database.connect() as c:
        row = dict(c.execute('SELECT * FROM ai_usage').fetchone())
    assert (row['status'], row['request_id'], row['total_tokens'], row['reasoning_tokens'], row['cached_tokens']) == ('success', 'resp-test', 30, 8, 5)
    assert 'source' not in str(row) and 'offline-test-secret' not in str(row)


def test_multiline_sse_json_and_completed_text_fallback(tmp_path):
    lines = ['data: {"type": "response.completed",', 'data: "response": {"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":"Život"}]}]}}', '']
    obj, _ = client(tmp_path, Response(lines))
    assert obj.generate('gpt-6.1-sol', 'rules', 'source') == 'Život'


@pytest.mark.parametrize('lines,code', [
    (sse({'type': 'response.output_text.delta', 'delta': 'partial'}), 'incomplete_stream'),
    (['data: invalid-json', ''], 'invalid_sse'),
    (sse(completed()), 'empty_output'),
    (sse({'type': 'response.incomplete', 'response': {'error': {'code': 'max_output_tokens'}}}), 'response_failed'),
    (sse({'type': 'response.output_text.delta', 'delta': 'x' * 256001}), 'output_too_large'),
])
def test_never_accepts_truncated_or_invalid_outputs(tmp_path, lines, code):
    obj, _ = client(tmp_path, Response(lines))
    with pytest.raises(ai_client.AIError, match=code): obj.generate('gpt-6-luna', 'rules', 'source')
    with database.connect() as c: assert c.execute('SELECT status FROM ai_usage').fetchone()[0] == 'failed'


@pytest.mark.parametrize('model', ['gpt-4o', 'gpt-6-sol', '', 'gpt-6-luna-extra'])
def test_unapproved_model_never_makes_request(tmp_path, model):
    obj, session = client(tmp_path, Response())
    with pytest.raises(ValueError, match='model_not_allowed'): obj.generate(model, 'rules', 'source')
    assert session.calls == []


@pytest.mark.parametrize('status,transient,quota', [(429, True, True), (500, True, False), (401, False, False), (403, False, False), (400, False, False)])
def test_http_error_classification_is_sanitized(tmp_path, status, transient, quota):
    obj, _ = client(tmp_path, Response(status=status))
    with pytest.raises(ai_client.AIError) as exc: obj.generate('gpt-6-luna', 'rules', 'source')
    assert (exc.value.code, exc.value.transient, exc.value.quota) == ('http_' + str(status), transient, quota)
    assert 'offline-test-secret' not in str(exc.value)


def test_network_errors_are_sanitized(tmp_path):
    obj, _ = client(tmp_path, requests.ConnectionError('offline-test-secret raw private endpoint'))
    with pytest.raises(ai_client.AIError, match='network_error') as exc: obj.generate('gpt-6-luna', 'rules', 'source')
    assert 'offline-test-secret' not in str(exc.value)


def test_completed_only_output_has_same_size_bound(tmp_path):
    obj,_=client(tmp_path,Response(sse(completed(output=[{'type':'message','content':[{'type':'output_text','text':'x'*256001}]}]))))
    with pytest.raises(ai_client.AIError,match='output_too_large'):obj.generate('gpt-6-luna','rules','source')
