import uuid

from django.db import models
from django.utils import timezone

from config import settings
from usuarios.models import Universidad

class Hilo(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    titulo = models.CharField(max_length=200)
    contenido = models.TextField()
    imagen = models.ImageField(upload_to='hilos/imagenes/', blank=True, null=True)
    imagen2 = models.ImageField(upload_to='hilos/imagenes/', blank=True, null=True)
    imagen3 = models.ImageField(upload_to='hilos/imagenes/', blank=True, null=True)
    imagen4 = models.ImageField(upload_to='hilos/imagenes/', blank=True, null=True)

    video = models.FileField(upload_to='hilos/videos/', blank=True, null=True)
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    universidad = models.ForeignKey(Universidad, on_delete=models.CASCADE, null=True, blank=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True, db_index=True)
    ultima_actividad = models.DateTimeField(default=timezone.now) 
    activo = models.BooleanField(default=True)

    likes = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='hilos_likes', blank=True )

    class Meta:
        ordering = ['-ultima_actividad']

    def __str__(self):
        return self.titulo

class Respuesta(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    contenido = models.TextField()
    imagen = models.ImageField(upload_to='respuestas/imagenes/', blank=True, null=True)
    video = models.FileField(upload_to='respuestas/videos/', blank=True, null=True)
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    hilo = models.ForeignKey(Hilo, on_delete=models.CASCADE, related_name='respuestas')
    respuesta_padre = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='respuestas_hijas')
    fecha_creacion = models.DateTimeField(auto_now_add=True, db_index=True)
    activo = models.BooleanField(default=True) 
    likes = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='respuestas_likeadas', blank=True)  

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.hilo.ultima_actividad = self.fecha_creacion
        # CORRECCIÓN: Solo actualizamos la fecha, no reescribimos toda la fila
        self.hilo.save(update_fields=['ultima_actividad'])

class Notificacion(models.Model):
    TIPO_LIKE_HILO = 'like_hilo'
    TIPO_COMENTARIO = 'comentario'
    TIPO_LIKE_RESPUESTA = 'like_respuesta'
    TIPO_SEGUIDOR = 'seguidor'
    TIPO_LIKE_SUGERENCIA = 'like_sug'
    TIPO_COMENTARIO_SUGERENCIA = 'coment_sug'
    
    TIPO_CHOICES = [
        (TIPO_LIKE_HILO, 'Like a hilo'),
        (TIPO_COMENTARIO, 'Comentario'),
        (TIPO_LIKE_RESPUESTA, 'Like a respuesta'),
        (TIPO_SEGUIDOR, 'Nuevo seguidor'),
        (TIPO_LIKE_SUGERENCIA, 'Like a sugerencia'),
        (TIPO_COMENTARIO_SUGERENCIA, 'Comentario en sugerencia'),
    ]

    destinatario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='notificaciones', db_index=True
    )
    actores = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name='notificaciones_generadas', blank=True
    )
    tipo = models.CharField(max_length=25, choices=TIPO_CHOICES)
    hilo = models.ForeignKey(Hilo, null=True, blank=True, on_delete=models.CASCADE)
    respuesta = models.ForeignKey(Respuesta, null=True, blank=True, on_delete=models.CASCADE)
    sugerencia = models.ForeignKey('Sugerencia', null=True, blank=True, on_delete=models.CASCADE)
    respuesta_sugerencia = models.ForeignKey('RespuestaSugerencia', null=True, blank=True, on_delete=models.CASCADE) 
    leido = models.BooleanField(default=False, db_index=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    ultima_actividad = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ['-ultima_actividad']
        indexes = [models.Index(fields=['destinatario', 'leido'])]

    def texto_nombres(self):
        actores = list(self.actores.all()[:2])
        total = self.actores.count()
        if total == 0:
            return ''
        if total == 1:
            return actores[0].username
        if total == 2:
            return f"{actores[0].username} y {actores[1].username}"
        return f"{actores[0].username}, {actores[1].username} y {total - 2} más"

    def texto_accion(self):
        total = self.actores.count()
        plural = total != 1
        textos = {
            self.TIPO_LIKE_HILO: 'les ha gustado tu hilo' if plural else 'le ha gustado tu hilo',
            self.TIPO_LIKE_RESPUESTA: 'les ha gustado tu comentario' if plural else 'le ha gustado tu comentario',
            self.TIPO_COMENTARIO: 'comentaron en tu hilo' if plural else 'comentó en tu hilo',
            self.TIPO_SEGUIDOR: 'empezaron a seguirte' if plural else 'empezó a seguirte',
            self.TIPO_LIKE_SUGERENCIA: 'apoyaron tu sugerencia' if plural else 'apoyó tu sugerencia',
            self.TIPO_COMENTARIO_SUGERENCIA: 'respondieron a tu sugerencia' if plural else 'respondió a tu sugerencia',
        }
        return textos.get(self.tipo, '')

    def __str__(self):
        return f"Notificación para {self.destinatario} ({self.tipo})"

class Sugerencia(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    contenido = models.TextField(verbose_name="Contenido de la sugerencia")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    #likes para las sugerencias
    likes = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='sugerencias_likes', blank=True)
    dislikes = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='sugerencias_dislikes', blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Sugerencia de {self.usuario} - {self.created_at.strftime('%d/%m/%Y')}"    

class RespuestaSugerencia(models.Model):
    sugerencia = models.ForeignKey(Sugerencia, on_delete=models.CASCADE, related_name='respuestas')
    respuesta_padre = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='respuestas_hijas')
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    contenido = models.TextField()
    fecha_creacion = models.DateTimeField(auto_now_add=True, db_index=True)
    likes = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='respuestas_sugerencia_likes', blank=True)

    class Meta:
        ordering = ['fecha_creacion']

    def __str__(self):
        return f"Respuesta de {self.autor} en sugerencia {self.sugerencia.pk}"