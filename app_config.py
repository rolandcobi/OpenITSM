"""Configuration resolution without filesystem, database or worker side effects."""
import os
import secrets
from datetime import timedelta
from pathlib import Path
from types import MappingProxyType

ENV_KEYS = frozenset(('ITSM_ENV','ITSM_DB','ITSM_SECRET_KEY','ITSM_INITIAL_ADMIN_PASSWORD',
    'ITSM_TLS','ITSM_HTTPS','ITSM_DEBUG','ITSM_ALLOWED_HOSTS','ITSM_CERT','ITSM_KEY',
    'ITSM_HOST','PORT','ITSM_HTTPS_PORT','ITSM_HTTP_REDIRECT','ITSM_THREADS',
    'ITSM_BACKUP','ITSM_CERT_HOSTS'))

def resolve_settings(overrides=None, environ=None):
    source = os.environ if environ is None else environ
    values = {k:source[k] for k in ENV_KEYS if k in source}
    overrides = dict(overrides or {})
    unknown = set(overrides) - ENV_KEYS - {'TESTING'}
    if unknown:
        raise ValueError('Unknown application configuration keys: '+', '.join(sorted(unknown)))
    testing = overrides.pop('TESTING',False)
    if not isinstance(testing,bool):
        raise ValueError('TESTING must be boolean')
    values.update(overrides)
    if any(not isinstance(v,str) for v in values.values()):
        raise ValueError('Environment configuration values must be strings')
    values.setdefault('ITSM_ENV','development')
    if values['ITSM_ENV'] not in ('development','test','production'):
        raise RuntimeError('ITSM_ENV must be development, test or production')
    for key in ('ITSM_TLS','ITSM_HTTPS','ITSM_DEBUG','ITSM_HTTP_REDIRECT','ITSM_BACKUP'):
        if key in values and values[key] not in ('0','1'):
            raise RuntimeError(key+' must be 0 or 1')
    for key,maximum in (('PORT',65535),('ITSM_HTTPS_PORT',65535),('ITSM_THREADS',1024)):
        value = values.get(key)
        if value is not None and (not value.isascii() or not value.isdigit() or not 1<=int(value)<=maximum):
            raise RuntimeError('Invalid '+key)
    secret = values.get('ITSM_SECRET_KEY')
    if secret is not None and (len(secret)<32 or secret=='CHANGE-ME-IN-PRODUCTION'):
        raise RuntimeError('ITSM_SECRET_KEY must contain at least 32 characters')
    if values['ITSM_ENV']=='production':
        if not secret: raise RuntimeError('Production requires ITSM_SECRET_KEY')
        if values.get('ITSM_HTTPS')!='1' or values.get('ITSM_TLS','1')=='0' or values.get('ITSM_DEBUG')=='1':
            raise RuntimeError('Production requires HTTPS secure cookies and debug disabled')
        if not values.get('ITSM_ALLOWED_HOSTS') or not any(h.strip() for h in values['ITSM_ALLOWED_HOSTS'].split(',')):
            raise RuntimeError('Production requires ITSM_ALLOWED_HOSTS')
        if not all(Path(values.get(k,'')).is_file() for k in ('ITSM_CERT','ITSM_KEY')):
            raise RuntimeError('Production requires configured ITSM_CERT and ITSM_KEY files')
    return MappingProxyType(values),testing

def resolve_secret(settings, path):
    secret = settings.get('ITSM_SECRET_KEY')
    if secret:
        return secret
    path = Path(path)
    if not path.exists():
        try:
            with path.open('x',encoding='utf-8') as stream:
                stream.write(secrets.token_hex(32))
            try: path.chmod(0o600)
            except OSError: pass
        except FileExistsError:
            pass
    return path.read_text(encoding='utf-8').strip()

def flask_configuration(settings, secret, testing=False):
    config = dict(SECRET_KEY=secret,TESTING=testing,DEBUG=settings.get('ITSM_DEBUG')=='1',MAX_CONTENT_LENGTH=10*1024*1024,
        SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=settings.get('ITSM_HTTPS')=='1',
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=30))
    if settings.get('ITSM_ALLOWED_HOSTS'):
        config['TRUSTED_HOSTS']=[h.strip() for h in settings['ITSM_ALLOWED_HOSTS'].split(',') if h.strip()]
    return config
