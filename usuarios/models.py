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

    def save(self, *args, **kwargs):
        if self.avatar and not self.avatar.name.endswith('.webp'):
            img = Image.open(self.avatar).convert('RGB')
            img.thumbnail((400, 400)) 
            output = BytesIO()
            img.save(output, format='WebP', quality=80)
            self.avatar.save(f"{self.username}_avatar.webp", ContentFile(output.getvalue()), save=False)
            
        if self.banner and not self.banner.name.endswith('.webp'):
            img = Image.open(self.banner).convert('RGB')
            img.thumbnail((1200, 400)) 
            output = BytesIO()
            img.save(output, format='WebP', quality=75)
            self.banner.save(f"{self.username}_banner.webp", ContentFile(output.getvalue()), save=False)
            
        super().save(*args, **kwargs)

    def __str__(self):
        return self.username

class Mensaje(models.Model):
    remitente = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='mensajes_enviados', on_delete=models.CASCADE, db_index=True)
    destinatario = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='mensajes_recibidos', on_delete=models.CASCADE, db_index=True)
    contenido = models.TextField(null=True, blank=True)
    imagen = models.ImageField(upload_to='chat_imagenes/', null=True, blank=True)
    fecha_envio = models.DateTimeField(auto_now_add=True, db_index=True)
    leido = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ['fecha_envio']
        indexes = [
            models.Index(fields=['remitente', 'destinatario']),
        ]

    def save(self, *args, **kwargs):
        if self.imagen and not self.imagen.name.endswith('.webp'):
            img = Image.open(self.imagen).convert('RGB')
            img.thumbnail((1080, 1080))
            output = BytesIO()
            img.save(output, format='WebP', quality=70)
            nombre_limpio = self.imagen.name.split('.')[0].split('/')[-1]
            self.imagen.save(f"{nombre_limpio}.webp", ContentFile(output.getvalue()), save=False)
            
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.remitente.username} a {self.destinatario.username}"


 