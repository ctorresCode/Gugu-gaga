from .models import AvisoGlobal, Notificacion
from django.conf import settings

def notificaciones_sin_leer(request):
    if request.user.is_authenticated:
        total = Notificacion.objects.filter(destinatario=request.user, leido=False).count()
    else:
        total = 0
    return {'total_notificaciones_sin_leer': total}

def supabase_globals(request):
    return {
        'SUPABASE_URL': getattr(settings, 'SUPABASE_URL', ''),
        'SUPABASE_ANON_KEY': getattr(settings, 'SUPABASE_ANON_KEY', '')
    }

def avisos_globales(request):
    if request.user.is_authenticated:
        avisos_pendientes = AvisoGlobal.objects.filter(activo=True).exclude(visto_por=request.user)
        return {'avisos_pendientes': avisos_pendientes}

    return {'avisos_pendientes': []}
    