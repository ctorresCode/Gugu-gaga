import json
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
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


limite_hilos = _apilar(_rl('hilos_min', '5/m'), _rl('hilos_hora', '30/h'))
limite_comentarios = _apilar(_rl('comentarios_min', '10/m'), _rl('comentarios_hora', '100/h'))
limite_sugerencias = _apilar(_rl('sugerencias_min', '5/m'), _rl('sugerencias_hora', '20/h'))
limite_likes = _apilar(_rl('likes', '60/m'))
limite_busqueda = _apilar(_rl('busqueda', '60/m', method='GET'))  # búsqueda mientras se escribe
limite_chat = _apilar(_rl('chat_min', '30/m'), _rl('chat_hora', '300/h'))
limite_seguir = _apilar(_rl('seguir', '30/m'))
limite_perfil = _apilar(_rl('perfil_hora', '10/h'))
limite_registro = _apilar(_rl('registro', '30/h', key=ip_key))  # IP: el campus comparte wifi

def _respuesta_htmx(mensaje, status):    
    resp = HttpResponse(status=204)
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
