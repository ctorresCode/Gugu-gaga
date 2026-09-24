import os
import django
from django.conf import settings

settings.configure(
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'univoz-local-cache',
        }
    },
    RATELIMIT_USE_CACHE='default',
    # Try testing with fail open setting if we need
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

# Test
print("Limit 1:", is_ratelimited(req, group='chat_min', key='user', rate='30/m', method='POST', increment=True))
print("Limit 2:", getattr(req, 'limited', False))

for i in range(35):
    limited = is_ratelimited(req, group='chat_min', key='user', rate='30/m', method='POST', increment=True)

print("Limit 35:", limited)
