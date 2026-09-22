from datetime import timedelta
from django.utils import timezone
from io import BytesIO
import random
import secrets
from PIL import Image
from django.core.files.base import ContentFile
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password


ALFABETO_RECUPERACION = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'

def normalizar_codigo(codigo):
    return ''.join(c for c in (codigo or '').upper() if c.isalnum())


class Universidad(models.Model):
    nombre = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.nombre

class UsuarioForo(AbstractUser):
    universidad = models.ForeignKey(Universidad, on_delete=models.SET_NULL, null=True)
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    seguidos = models.ManyToManyField('self', symmetrical=False, related_name='seguidores', blank=True)
    email = models.EmailField(unique=True, blank=True, null=True)
    descripcion = models.TextField(blank=True, null=True)
    banner = models.ImageField(upload_to='banners/', null=True, blank=True)
    codigo_recuperacion_hash = models.CharField(max_length=128, blank=True, default='')
    acepto_terminos_fecha = models.DateTimeField(null=True, blank=True)
    acepto_terminos_version = models.CharField(max_length=10, blank=True, default='')

    reset_password_codigo_hash = models.CharField(max_length=128,blank=True, null=True)
    reset_password_expira = models.DateTimeField(blank=True, null=True)
    reset_password_intentos = models.PositiveSmallIntegerField(default=0)

    def __str__(self):
        return self.username

    def generar_codigo_recuperacion(self):
        """Genera un código nuevo, guarda solo su hash y devuelve el texto plano (mostrar una sola vez)."""
        crudo = ''.join(secrets.choice(ALFABETO_RECUPERACION) for _ in range(16))
        self.codigo_recuperacion_hash = make_password(crudo)
        self.save(update_fields=['codigo_recuperacion_hash'])
        return '-'.join(crudo[i:i + 4] for i in range(0, 16, 4))

    def verificar_codigo_recuperacion(self, codigo):
        if not self.codigo_recuperacion_hash:
            return False
        return check_password(normalizar_codigo(codigo), self.codigo_recuperacion_hash)

    def generar_codigo_reset_password(self):
        codigo = f"{random.randint(0, 999999):06d}"
        self.reset_password_codigo_hash = make_password(codigo)
        self.reset_password_expira = timezone.now() + timedelta(minutes=15)
        self.reset_password_intentos = 0
        self.save(update_fields=['reset_password_codigo_hash', 'reset_password_expira', 'reset_password_intentos'])
        return codigo

    def verificar_codigo_reset_password(self, codigo):
        if not self.reset_password_codigo_hash or not self.reset_password_expira:
            return False
        if timezone.now() > self.reset_password_expira:
            return False
        if self.reset_password_intentos >= 5:
            return False

        
        valido = check_password(codigo, self.reset_password_codigo_hash)
        if not valido:
            self.reset_password_intentos += 1
            self.save(update_fields=['reset_password_intentos'])
        return valido

    def limpiar_codigo_reset_password(self):
        self.reset_password_codigo_hash = None
        self.reset_password_expira = None
        self.reset_password_intentos = 0
        self.save(update_fields=['reset_password_codigo_hash', 'reset_password_expira', 'reset_password_intentos'])

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


 