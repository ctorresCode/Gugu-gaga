from io import BytesIO
from PIL import Image
from django.core.files.base import ContentFile
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings


class Universidad(models.Model):
    nombre = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.nombre

class UsuarioForo(AbstractUser):
    universidad = models.ForeignKey(Universidad, on_delete=models.SET_NULL, null=True)
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    seguidos = models.ManyToManyField('self', symmetrical=False, related_name='seguidores', blank=True)
    email = None
    descripcion = models.TextField(blank=True, null=True)
    banner = models.ImageField(upload_to='banners/', null=True, blank=True)

    def __str__(self):
        return self.username

class Mensaje(models.Model):
    remitente = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='mensajes_enviados', on_delete=models.CASCADE, db_index=True)
    destinatario = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='mensajes_recibidos', on_delete=models.CASCADE, db_index=True)
    mensaje_respondido = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='respuestas')
    contenido = models.TextField(null=True, blank=True)
    imagen = models.ImageField(upload_to='chat_imagenes/',  blank=True, null=True)
    imagen2 = models.ImageField(upload_to='chat_imagenes/', blank=True, null=True)
    imagen3 = models.ImageField(upload_to='chat_imagenes/', blank=True, null=True)
    imagen4 = models.ImageField(upload_to='chat_imagenes/', blank=True, null=True)
    fecha_envio = models.DateTimeField(auto_now_add=True, db_index=True)
    leido = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ['fecha_envio']
        indexes = [
            models.Index(fields=['remitente', 'destinatario']),
        ]

    def __str__(self):
        return f"{self.remitente.username} a {self.destinatario.username}"


 