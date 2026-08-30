from .models import Notificacion

def notificaciones_sin_leer(request):
    if request.user.is_authenticated:
        total = Notificacion.objects.filter(destinatario=request.user, leido=False).count()
    else:
        total = 0
    return {'total_notificaciones_sin_leer': total}