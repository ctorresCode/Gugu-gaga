from django.core.cache import cache
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from foro.models import AvisoGlobal, Hilo, Notificacion, Respuesta
from foro.notificaciones import notificar, retirar_notificacion
from usuarios.models import UsuarioForo


def _usuarios(pk_set):
    return UsuarioForo.objects.filter(pk__in=pk_set)


@receiver(m2m_changed, sender=Hilo.likes.through)
def gestionar_like_hilo(sender, instance, action, pk_set, reverse, **kwargs):
    if reverse or not pk_set or instance.autor is None:
        return

    if action == 'post_add':
        for actor in _usuarios(pk_set):
            notificar(instance.autor, Notificacion.TIPO_LIKE_HILO, actor, hilo=instance)
    elif action == 'post_remove':
        retirar_notificacion(instance.autor, Notificacion.TIPO_LIKE_HILO, pk_set, hilo=instance)


@receiver(m2m_changed, sender=Respuesta.likes.through)
def gestionar_like_respuesta(sender, instance, action, pk_set, reverse, **kwargs):
    if reverse or not pk_set or instance.autor is None:
        return

    objetos = {'hilo': instance.hilo, 'respuesta': instance}
    if action == 'post_add':
        for actor in _usuarios(pk_set):
            notificar(instance.autor, Notificacion.TIPO_LIKE_RESPUESTA, actor, **objetos)
    elif action == 'post_remove':
        retirar_notificacion(instance.autor, Notificacion.TIPO_LIKE_RESPUESTA, pk_set, **objetos)


@receiver(post_save, sender=Respuesta)
def notificar_comentario(sender, instance, created, **kwargs):
    if not created or instance.autor is None:
        return

    if instance.respuesta_padre_id:
        destinatario = instance.respuesta_padre.autor
    else:
        destinatario = instance.hilo.autor

    # Cada comentario es su propia notificación (enlaza a esa respuesta concreta).
    if destinatario is None or destinatario == instance.autor:
        return
    notif = Notificacion.objects.create(
        destinatario=destinatario,
        tipo=Notificacion.TIPO_COMENTARIO,
        hilo=instance.hilo,
        respuesta=instance,
    )
    notif.actores.add(instance.autor)


@receiver(m2m_changed, sender=UsuarioForo.seguidos.through)
def notificar_nuevo_seguidor(sender, instance, action, pk_set, reverse, **kwargs):
    if reverse or not pk_set:
        return

    if action == 'post_add':
        for destinatario in _usuarios(pk_set):
            notificar(destinatario, Notificacion.TIPO_SEGUIDOR, instance, hilo=None)
    elif action == 'post_remove':
        for destinatario in _usuarios(pk_set):
            retirar_notificacion(destinatario, Notificacion.TIPO_SEGUIDOR, [instance.pk], hilo=None)


@receiver([post_save, post_delete], sender=AvisoGlobal)
def invalidar_cache_avisos(sender, **kwargs):
    from foro.context_processors import CLAVE_AVISOS_ACTIVOS
    cache.delete(CLAVE_AVISOS_ACTIVOS)
