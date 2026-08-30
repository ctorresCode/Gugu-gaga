from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver
from .models import Hilo, Respuesta, Notificacion
from usuarios.models import UsuarioForo

@receiver(m2m_changed, sender=Hilo.likes.through)
def gestionar_like_hilo(sender, instance, action, pk_set, **kwargs):
    destinatario = instance.autor
    if destinatario is None or not pk_set:
        return

    if action == 'post_add':
        for actor_id in pk_set:
            if actor_id == destinatario.id:
                continue
            notif, _ = Notificacion.objects.get_or_create(
                destinatario=destinatario, tipo=Notificacion.TIPO_LIKE_HILO, hilo=instance,
            )
            notif.actores.add(actor_id)
            notif.leido = False
            notif.save(update_fields=['leido'])

    elif action == 'post_remove':
        try:
            notif = Notificacion.objects.get(
                destinatario=destinatario, tipo=Notificacion.TIPO_LIKE_HILO, hilo=instance,
            )
            notif.actores.remove(*pk_set)
            if not notif.actores.exists():
                notif.delete()
        except Notificacion.DoesNotExist:
            pass


@receiver(m2m_changed, sender=Respuesta.likes.through)
def gestionar_like_respuesta(sender, instance, action, pk_set, **kwargs):
    destinatario = instance.autor
    if destinatario is None or not pk_set:
        return

    if action == 'post_add':
        for actor_id in pk_set:
            if actor_id == destinatario.id:
                continue
            notif, _ = Notificacion.objects.get_or_create(
                destinatario=destinatario, 
                tipo=Notificacion.TIPO_LIKE_RESPUESTA, 
                hilo=instance.hilo,
                respuesta=instance
            )
            notif.actores.add(actor_id)
            notif.leido = False
            notif.save(update_fields=['leido'])

    elif action == 'post_remove':
        try:
            notif = Notificacion.objects.get(
                destinatario=destinatario, 
                tipo=Notificacion.TIPO_LIKE_RESPUESTA, 
                hilo=instance.hilo,
                respuesta=instance
            )
            notif.actores.remove(*pk_set)
            if not notif.actores.exists():
                notif.delete()
        except Notificacion.DoesNotExist:
            pass


@receiver(post_save, sender=Respuesta)
def notificar_comentario(sender, instance, created, **kwargs):
    if not created:
        return
    
    if getattr(instance, 'respuesta_padre', None):
        destinatario = instance.respuesta_padre.autor
    else:
        destinatario = instance.hilo.autor

    # Evita que el usuario se notifique a sí mismo
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
        for destinatario_id in pk_set:
            if destinatario_id == instance.id:
                continue
            notif, _ = Notificacion.objects.get_or_create(
                destinatario_id=destinatario_id, tipo=Notificacion.TIPO_SEGUIDOR, hilo=None,
            )
            notif.actores.add(instance)
            notif.leido = False
            notif.save(update_fields=['leido'])

    elif action == 'post_remove':
        for destinatario_id in pk_set:
            try:
                notif = Notificacion.objects.get(
                    destinatario_id=destinatario_id, tipo=Notificacion.TIPO_SEGUIDOR, hilo=None,
                )
                notif.actores.remove(instance)
                if not notif.actores.exists():
                    notif.delete()
            except Notificacion.DoesNotExist:
                continue