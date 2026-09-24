import django
from django.conf import settings
from django.core.cache.backends.base import BaseCache

class DummyFailingCache(BaseCache):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    def add(self, key, value, timeout=None, version=None):
        return False
    def get(self, key, default=None, version=None):
        return None
    def set(self, key, value, timeout=None, version=None):
        return None
    def incr(self, key, delta=1, version=None):
        # django-redis with IGNORE_EXCEPTIONS = True usually returns None or swallows
        return None

settings.configure(
    CACHES={
        'default': {
            'BACKEND': 'test_silent_cache.DummyFailingCache',
        }
    },
    RATELIMIT_USE_CACHE='default',
)
django.setup()

from django_ratelimit.core import is_ratelimited
from django.http import HttpRequest

class DummyUser:
    pk = 1
    is_authenticated = True

req = HttpRequest()
req.META['REMOTE_ADDR'] = '127.0.0.1'
req.user = DummyUser()
req.method = 'POST'

print("Silent Cache Limit 1:", is_ratelimited(req, group='chat_min', key='user', rate='30/m', method='POST', increment=True))
