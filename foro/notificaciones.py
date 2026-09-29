"""
Creación y retirada de notificaciones agrupadas.

Una notificación agrupa a todos los actores de la misma acción sobre el mismo objeto
("ana, bob y 3 más apoyaron tu sugerencia"). Buscamos con filter().first() en vez de
get_or_create() porque sin una restricción UNIQUE en la BD dos peticiones simultáneas
pueden crear duplicados, y get() reventaría luego con MultipleObjectsReturned.
"""
from foro.models import Notificacion


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
