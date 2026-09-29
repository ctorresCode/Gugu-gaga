from django.conf import settings

from foro.models import AvisoGlobal, Notificacion
from usuarios.models import Mensaje


def notificaciones_sin_leer(request):
    if not request.user.is_authenticated:
        return {'total_notificaciones_sin_leer': 0, 'total_mensajes_sin_leer': 0}
    return {
        'total_notificaciones_sin_leer': Notificacion.objects.filter(destinatario=request.user, leido=False).count(),
        'total_mensajes_sin_leer': Mensaje.objects.filter(destinatario=request.user, leido=False).count(),
    }


def supabase_globals(request):
    # La anon key es pública por diseño; lo que protege los datos son los permisos/RLS de la BD
    # (ver foro/migrations/0021_seguridad_supabase.py).
    return {
        'SUPABASE_URL': getattr(settings, 'SUPABASE_URL', ''),
        'SUPABASE_ANON_KEY': getattr(settings, 'SUPABASE_ANON_KEY', ''),
    }


def avisos_globales(request):
    if request.user.is_authenticated:
        return {'avisos_pendientes': AvisoGlobal.objects.filter(activo=True).exclude(visto_por=request.user)}
    return {'avisos_pendientes': []}
