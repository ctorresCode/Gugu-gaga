from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.utils.functional import SimpleLazyObject

from foro.models import AvisoGlobal
from foro.notificaciones import contadores_usuario

CLAVE_AVISOS_ACTIVOS = 'avisos_activos_ids'


def notificaciones_sin_leer(request):
    if not request.user.is_authenticated:
        return {'total_notificaciones_sin_leer': 0, 'total_mensajes_sin_leer': 0}

    # Perezoso: solo se consulta si la plantilla usa los contadores, y ambos salen de UNA consulta.
    def contadores():
        if not hasattr(request, '_contadores_univoz'):
            request._contadores_univoz = contadores_usuario(request.user)
        return request._contadores_univoz

    return {
        'total_notificaciones_sin_leer': SimpleLazyObject(lambda: contadores()['notificaciones']),
        'total_mensajes_sin_leer': SimpleLazyObject(lambda: contadores()['mensajes']),
    }


def _origen(url):
    partes = urlparse(url if '://' in url else f'https://{url}')
    return f'{partes.scheme}://{partes.netloc}' if partes.netloc else ''


def supabase_globals(request):
    # La anon key es pública por diseño; lo que protege los datos son los permisos/RLS de la BD
    # (ver foro/migrations/0021_seguridad_supabase.py).
    dominio_media = getattr(settings, 'AWS_S3_CUSTOM_DOMAIN', None)
    return {
        'SUPABASE_URL': getattr(settings, 'SUPABASE_URL', ''),
        'SUPABASE_ANON_KEY': getattr(settings, 'SUPABASE_ANON_KEY', ''),
        'MEDIA_ORIGIN': _origen(dominio_media) if dominio_media else '',
    }


def ids_avisos_activos():
    """Ids de avisos activos, cacheados. Casi siempre es una lista vacía y así no se consulta la BD."""
    ids = cache.get(CLAVE_AVISOS_ACTIVOS)
    if ids is None:
        ids = list(AvisoGlobal.objects.filter(activo=True).values_list('id', flat=True))
        cache.set(CLAVE_AVISOS_ACTIVOS, ids, 300)
    return ids


def avisos_globales(request):
    if not request.user.is_authenticated:
        return {'avisos_pendientes': []}

    def pendientes():
        ids = ids_avisos_activos()
        if not ids:
            return []
        return list(AvisoGlobal.objects.filter(id__in=ids).exclude(visto_por=request.user))

    return {'avisos_pendientes': SimpleLazyObject(pendientes)}
