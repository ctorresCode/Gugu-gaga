import json
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django_ratelimit.core import get_usage
from django_ratelimit.decorators import ratelimit

from config.utils import ip_key
from foro.utils import es_htmx


def _rl(group, rate, key='user', method='POST'):
    return ratelimit(key=key, rate=rate, group=group, method=method, block=False)


def _apilar(*decoradores):
    def aplicar(vista):
        for decorador in decoradores:
            vista = decorador(vista)
        return vista
    return aplicar


# Acciones donde cada petición ES la acción (likes, seguir...): cuentan todas las peticiones.
limite_likes = _apilar(_rl('likes', '60/m'))
limite_busqueda = _apilar(_rl('busqueda', '60/m', method='GET'))  # búsqueda mientras se escribe
limite_chat = _apilar(_rl('chat_min', '30/m'), _rl('chat_hora', '300/h'))
limite_seguir = _apilar(_rl('seguir', '30/m'))
limite_perfil = _apilar(_rl('perfil_hora', '10/h'))
limite_registro = _apilar(_rl('registro', '1000/h', key=ip_key))  # alto a propósito: wifi compartido de universidades
limite_reportes = _apilar(_rl('reportes_hora', '20/h'))


# Publicaciones: solo cuentan las que se guardan de verdad, así un error de validación no gasta cuota.
CUOTAS_PUBLICACION = {
    'hilos': (('hilos_min', '5/m'), ('hilos_hora', '30/h')),
    'comentarios': (('comentarios_min', '10/m'), ('comentarios_hora', '100/h')),
    'sugerencias': (('sugerencias_min', '5/m'), ('sugerencias_hora', '20/h')),
}


def _uso(request, grupo, rate, incrementar):
    return get_usage(request, group=grupo, key='user', rate=rate, method='POST', increment=incrementar)


def cuota_agotada(request, tipo):
    """True si el usuario ya llegó al límite de `tipo` (no consume cuota)."""
    for grupo, rate in CUOTAS_PUBLICACION[tipo]:
        uso = _uso(request, grupo, rate, incrementar=False)
        if uso and uso['count'] >= uso['limit']:
            return True
    return False


def consumir_cuota(request, tipo):
    """Registra una publicación exitosa de `tipo`."""
    for grupo, rate in CUOTAS_PUBLICACION[tipo]:
        _uso(request, grupo, rate, incrementar=True)


def _respuesta_htmx(mensaje, status):
    # htmx no hace swap de respuestas 4xx/5xx por defecto; el toast lo muestra base.html vía HX-Trigger.
    resp = HttpResponse(status=status)
    resp['HX-Trigger'] = json.dumps({'mostrarError': mensaje})
    return resp


def limite_excedido(request, mensaje, destino='/'):
    """429 para htmx/AJAX; mensaje + redirect para navegación normal."""
    if es_htmx(request):
        resp = _respuesta_htmx(mensaje, 429)
        resp['Retry-After'] = '60'
        return resp
    messages.error(request, mensaje)
    return redirect(destino)


def error_peticion(request, mensaje, destino='/', status=400):
    """Error de validación: status + toast para htmx; mensaje + redirect para navegación normal."""
    if es_htmx(request):
        return _respuesta_htmx(mensaje, status)
    messages.error(request, mensaje)
    return redirect(destino)
