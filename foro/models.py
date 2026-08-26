from django.db import models
from django.utils import timezone

from config import settings
from usuarios.models import Universidad

# Create your models here.
class Hilo(models.Model):
    titulo = models.CharField(max_length=200)
    contenido = models.TextField()
    imagen = models.ImageField(upload_to='hilos/imagenes/', blank=True, null=True) 
    video = models.FileField(upload_to='hilos/videos/', blank=True, null=True)
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    universidad = models.ForeignKey(Universidad, on_delete=models.CASCADE, null=True, blank=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    ultima_actividad = models.DateTimeField(default=timezone.now) 
    activo = models.BooleanField(default=True)

    likes = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='hilos_likes', blank=True )

    class Meta:
        ordering = ['-ultima_actividad']

    def __str__(self):
        return self.titulo

class Respuesta(models.Model):
    contenido = models.TextField()
    imagen = models.ImageField(upload_to='respuestas/imagenes/', blank=True, null=True)
    video = models.FileField(upload_to='respuestas/videos/', blank=True, null=True)
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    hilo = models.ForeignKey(Hilo, on_delete=models.CASCADE, related_name='respuestas')
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    activo = models.BooleanField(default=True)    

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.hilo.ultima_actividad = self.fecha_creacion
        self.hilo.save()




