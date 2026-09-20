from .models import Notificacion
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