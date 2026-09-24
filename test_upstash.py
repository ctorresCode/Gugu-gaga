import django
from django.conf import settings

# Configure minimal Django settings with the Upstash URL pattern
settings.configure(
    CACHES={
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': 'rediss://default:password@optimal-gobbler-296063.upstash.io:6379',
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
                'CONNECTION_POOL_KWARGS': {'ssl_cert_reqs': None}
            }
        }
    }
)
django.setup()

from django.core.cache import cache

try:
    print("Testing Redis client initialization...")
    # This triggers the client setup and URL parsing
    client = cache.client.get_client()
    print("Client initialized successfully.")
    
    # Check what parameters where extracted
    print("Connection params:", client.connection_pool.connection_kwargs)
except Exception as e:
    import traceback
    traceback.print_exc()
