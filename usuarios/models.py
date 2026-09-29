from datetime import timedelta
import secrets
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

ALFABETO_RECUPERACION = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'

RESET_MINUTOS = 15            
RESET_MAX_INTENTOS = 5        
RESET_COOLDOWN_SEGUNDOS = 60  
MAX_DESCRIPCION = 500


def normalizar_codigo(codigo):
    return ''.join(c for c in (codigo or '').upper() if c.isalnum())


def normalizar_email(email):
    """'' -> None (el campo es unique y nullable) y minúsculas para que la unicidad no dependa del caso."""
    email = (email or '').strip().lower()
    return email or None


class Universidad(models.Model):
    nombre = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.nombre

    @staticmethod
    def cacheadas():
        """Lista de universidades cacheada 24h (cambia muy poco)."""
        from django.core.cache import cache
        universidades = cache.get('universidades_list')
        if universidades is None:
            universidades = list(Universidad.objects.order_by('nombre'))
            cache.set('universidades_list', universidades, 86400)
        return universidades

class UsuarioForo(AbstractUser):
    universidad = models.ForeignKey(Universidad, on_delete=models.SET_NULL, null=True)
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    seguidos = models.ManyToManyField('self', symmetrical=False, related_name='seguidores', blank=True)
    email = models.EmailField(unique=True, blank=True, null=True)
    descripcion = models.TextField(max_length=MAX_DESCRIPCION, blank=True, null=True)
    banner = models.ImageField(upload_to='banners/', null=True, blank=True)
    codigo_recuperacion_hash = models.CharField(max_length=128, blank=True, default='')
    acepto_terminos_fecha = models.DateTimeField(null=True, blank=True)
    acepto_terminos_version = models.CharField(max_length=10, blank=True, default='')

    reset_password_codigo_hash = models.CharField(max_length=128, blank=True, null=True)
    reset_password_expira = models.DateTimeField(blank=True, null=True)
    reset_password_intentos = models.PositiveSmallIntegerField(default=0)

    # Cambio de email pendiente de confirmar con un código enviado a la nueva dirección.
    email_pendiente = models.EmailField(blank=True, null=True)
    email_codigo_hash = models.CharField(max_length=128, blank=True, null=True)
    email_codigo_expira = models.DateTimeField(blank=True, null=True)
    email_codigo_intentos = models.PositiveSmallIntegerField(default=0)

    def __str__(self):
        return self.username

    def save(self, *args, **kwargs):
        # create_user()/createsuperuser guardan '' si no se da email, lo que choca con unique=True.
        self.email = normalizar_email(self.email)
        super().save(*args, **kwargs)

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

    def puede_pedir_codigo_reset(self):
        """False si ya se generó un código hace menos de RESET_COOLDOWN_SEGUNDOS."""
        if not self.reset_password_expira:
            return True
        creado = self.reset_password_expira - timedelta(minutes=RESET_MINUTOS)
        return (timezone.now() - creado).total_seconds() >= RESET_COOLDOWN_SEGUNDOS

    def generar_codigo_reset_password(self):
        codigo = f"{secrets.randbelow(1000000):06d}"
        self.reset_password_codigo_hash = make_password(codigo)
        self.reset_password_expira = timezone.now() + timedelta(minutes=RESET_MINUTOS)
        self.reset_password_intentos = 0
        self.save(update_fields=['reset_password_codigo_hash', 'reset_password_expira', 'reset_password_intentos'])
        return codigo

    def verificar_codigo_reset_password(self, codigo):
        if not self.reset_password_codigo_hash or not self.reset_password_expira:
            return False
        if timezone.now() > self.reset_password_expira:
            return False

        UsuarioForo.objects.filter(pk=self.pk).update(
            reset_password_intentos=models.F('reset_password_intentos') + 1
        )
        self.refresh_from_db(fields=['reset_password_intentos', 'reset_password_codigo_hash', 'reset_password_expira'])

        if not self.reset_password_codigo_hash:
            return False
        if self.reset_password_intentos > RESET_MAX_INTENTOS:
            return False

        return check_password(codigo, self.reset_password_codigo_hash)

    def generar_codigo_cambio_email(self, nuevo_email):
        codigo = f"{secrets.randbelow(1000000):06d}"
        self.email_pendiente = normalizar_email(nuevo_email)
        self.email_codigo_hash = make_password(codigo)
        self.email_codigo_expira = timezone.now() + timedelta(minutes=RESET_MINUTOS)
        self.email_codigo_intentos = 0
        self.save(update_fields=['email_pendiente', 'email_codigo_hash', 'email_codigo_expira', 'email_codigo_intentos'])
        return codigo

    def puede_pedir_codigo_email(self):
        if not self.email_codigo_expira:
            return True
        creado = self.email_codigo_expira - timedelta(minutes=RESET_MINUTOS)
        return (timezone.now() - creado).total_seconds() >= RESET_COOLDOWN_SEGUNDOS

    def confirmar_cambio_email(self, codigo):
        """Si el código es correcto y el email sigue libre, lo aplica. Devuelve True/False."""
        if not self.email_pendiente or not self.email_codigo_hash or not self.email_codigo_expira:
            return False
        if timezone.now() > self.email_codigo_expira:
            return False

        UsuarioForo.objects.filter(pk=self.pk).update(email_codigo_intentos=models.F('email_codigo_intentos') + 1)
        self.refresh_from_db(fields=['email_codigo_intentos'])
        if self.email_codigo_intentos > RESET_MAX_INTENTOS:
            return False
        if not check_password(normalizar_codigo(codigo), self.email_codigo_hash):
            return False
        if UsuarioForo.objects.filter(email__iexact=self.email_pendiente).exclude(pk=self.pk).exists():
            return False

        self.email = self.email_pendiente
        self.cancelar_cambio_email(commit=False)
        self.save(update_fields=['email', 'email_pendiente', 'email_codigo_hash', 'email_codigo_expira', 'email_codigo_intentos'])
        return True

    def cancelar_cambio_email(self, commit=True):
        self.email_pendiente = None
        self.email_codigo_hash = None
        self.email_codigo_expira = None
        self.email_codigo_intentos = 0
        if commit:
            self.save(update_fields=['email_pendiente', 'email_codigo_hash', 'email_codigo_expira', 'email_codigo_intentos'])

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
