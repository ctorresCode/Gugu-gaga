from django.conf import settings


def get_client_ip(request):
    """
    IP real del cliente, sin fiarse de cabeceras que el propio cliente puede inventar.

    - BEHIND_CLOUDFLARE=True: usa CF-Connecting-IP (Cloudflare la sobrescribe siempre).
    - PROXY_COUNT=N: cada proxy de confianza AÑADE una IP al final de X-Forwarded-For, así que
      la IP real es la N-ésima empezando por la derecha. Todo lo que está más a la izquierda
      lo pudo escribir el cliente.
    - PROXY_COUNT=0: conexión directa, solo REMOTE_ADDR.
    """
    if getattr(settings, 'BEHIND_CLOUDFLARE', False):
        cf_ip = request.META.get('HTTP_CF_CONNECTING_IP', '').strip()
        if cf_ip:
            return cf_ip

    proxy_count = getattr(settings, 'PROXY_COUNT', 0)
    if proxy_count > 0:
        ips = [ip.strip() for ip in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',') if ip.strip()]
        if len(ips) >= proxy_count:
            return ips[-proxy_count]

    return request.META.get('REMOTE_ADDR')


def ip_key(group, request):
    """Clave de django-ratelimit basada en la IP real."""
    return get_client_ip(request)
