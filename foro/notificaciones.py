"""
Creación y retirada de notificaciones agrupadas.

Una notificación agrupa a todos los actores de la misma acción sobre el mismo objeto
("ana, bob y 3 más apoyaron tu sugerencia"). Buscamos con filter().first() en vez de
get_or_create() porque sin una restricción UNIQUE en la BD dos peticiones simultáneas
pueden crear duplicados, y get() reventaría luego con MultipleObjectsReturned.
"""
from django.db.models import Count, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce

from foro.models import Notificacion
from usuarios.models import Mensaje, UsuarioForo


def _contar(queryset, campo):
    subconsulta = (
        queryset.filter(**{campo: OuterRef('pk')})
        .order_by().values(campo).annotate(total=Count('*')).values('total')
    )
    return Coalesce(Subquery(subconsulta, output_field=IntegerField()), Value(0))


def _ultimo_id(queryset, campo):
    return Coalesce(
        Subquery(queryset.filter(**{campo: OuterRef('pk')}).order_by('-id').values('id')[:1]),
        Value(0),
    )


def contadores_usuario(usuario):
    """
    Notificaciones y mensajes sin leer + id del último mensaje, en UNA sola consulta
    (cada consulta es un viaje de red a la base de datos).
    """
    fila = (
        UsuarioForo.objects.filter(pk=usuario.pk)
        .annotate(
            _n_notificaciones=_contar(Notificacion.objects.filter(leido=False), 'destinatario'),
            _n_mensajes=_contar(Mensaje.objects.filter(leido=False), 'destinatario'),
            _ultimo_recibido=_ultimo_id(Mensaje.objects.all(), 'destinatario'),
            _ultimo_enviado=_ultimo_id(Mensaje.objects.all(), 'remitente'),
        )
        .values('_n_notificaciones', '_n_mensajes', '_ultimo_recibido', '_ultimo_enviado')
        .first()
    ) or {}
    return {
        'notificaciones': fila.get('_n_notificaciones', 0),
        'mensajes': fila.get('_n_mensajes', 0),
        'ultimo_mensaje_id': max(fila.get('_ultimo_recibido', 0), fila.get('_ultimo_enviado', 0)),
    }


def notificar(destinatario, tipo, actor, actualizar=None, **objetos):
    """
    Añade `actor` a la notificación (destinatario, tipo, **objetos), creándola si no existe,
    y la marca como no leída. `actualizar` permite cambiar campos extra (p. ej. la última respuesta).
    """
    if destinatario is None or actor is None or destinatario.pk == actor.pk:
        return None

    notif = (
        Notificacion.objects.filter(destinatario=destinatario, tipo=tipo, **objetos)
        .order_by('-ultima_actividad')
        .first()
    )
    if notif is None:
        notif = Notificacion.objects.create(destinatario=destinatario, tipo=tipo, **(actualizar or {}), **objetos)
    else:
        for campo, valor in (actualizar or {}).items():
            setattr(notif, campo, valor)
        notif.leido = False
        notif.save()  # también refresca ultima_actividad (auto_now)

    notif.actores.add(actor)
    return notif


def retirar_notificacion(destinatario, tipo, actor_ids, **objetos):
    """Quita a los actores; borra la notificación si se queda vacía."""
    if destinatario is None or not actor_ids:
        return
    for notif in Notificacion.objects.filter(destinatario=destinatario, tipo=tipo, **objetos):
        notif.actores.remove(*actor_ids)
        if not notif.actores.exists():
            notif.delete()
