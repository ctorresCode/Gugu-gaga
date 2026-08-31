from django.contrib import admin
from foro.models import Hilo, Respuesta, RespuestaSugerencia, Sugerencia

admin.site.register(Hilo)
admin.site.register(Respuesta)

@admin.register(Sugerencia)
class SugerenciasAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'contenido', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('contenido',)

@admin.register(RespuestaSugerencia)
class RespuestaSugerenciaAdmin(admin.ModelAdmin):
    list_display = ('autor', 'sugerencia', 'respuesta_padre', 'fecha_creacion')
    list_filter = ('fecha_creacion',)
    search_fields = ('contenido',)