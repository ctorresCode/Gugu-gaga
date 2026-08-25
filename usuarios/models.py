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

    def __str__(self):
        return self.username

class Mensaje(models.Model):
    remitente = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='mensajes_enviados', on_delete=models.CASCADE)
    destinatario = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='mensajes_recibidos', on_delete=models.CASCADE)
    contenido = models.TextField()
    fecha_envio = models.DateTimeField(auto_now_add=True)
    leido = models.BooleanField(default=False)

    class Meta:
        ordering = ['fecha_envio']

    def __str__(self):
        return f"{self.remitente.username} a {self.destinatario.username}"