"""Origin authorization. Identity is accepted only from a verified Access JWT."""
import os
import re
from functools import lru_cache, wraps
from flask import abort, g, request

@lru_cache(maxsize=4)
def key_client(issuer):
    from jwt import PyJWKClient
    return PyJWKClient(issuer + '/cdn-cgi/access/certs', cache_jwk_set=True, lifespan=300, timeout=5)

def verified_access_claims(token):
    team = os.getenv('CF_ACCESS_TEAM', '').removeprefix('https://').rstrip('/')
    if team.endswith('.cloudflareaccess.com'): team = team[:-len('.cloudflareaccess.com')]
    audience = os.getenv('CF_ACCESS_AUD', '')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}', team) or not audience or not os.getenv('SECRET_KEY'):
        abort(503, description='Správa nie je nakonfigurovaná.')
    if not token: abort(403)
    issuer = 'https://' + team + '.cloudflareaccess.com'
    try:
        import jwt
        key = key_client(issuer).get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=['RS256'], audience=audience, issuer=issuer,
                          options={'require': ['exp', 'iat', 'iss', 'aud', 'sub']}, leeway=0)
    except Exception:
        abort(403)

def access_required(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        g.access_claims = verified_access_claims(request.headers.get('Cf-Access-Jwt-Assertion', ''))
        return handler(*args, **kwargs)
    return wrapped
