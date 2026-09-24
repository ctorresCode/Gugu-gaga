from django.contrib import admin
from foro.models import AvisoGlobal, Hilo, Notificacion, Respuesta, RespuestaSugerencia, Sugerencia

@admin.register(Hilo)
class HiloAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'autor', 'universidad', 'fecha_creacion', 'activo')
    list_filter = ('activo', 'universidad', 'fecha_creacion')
    search_fields = ('titulo', 'contenido')
    raw_id_fields = ('autor', 'universidad')

@admin.register(Respuesta)
class RespuestaAdmin(admin.ModelAdmin):
    list_display = ('autor', 'hilo', 'fecha_creacion', 'activo')
    list_filter = ('activo', 'fecha_creacion')
    search_fields = ('contenido',)
    raw_id_fields = ('autor', 'hilo', 'respuesta_padre')

@admin.register(Notificacion)
class NotificacionAdmin(admin.ModelAdmin):
    list_display = ('destinatario', 'tipo', 'leido', 'fecha_creacion')
    list_filter = ('tipo', 'leido', 'fecha_creacion')
    raw_id_fields = ('destinatario', 'hilo', 'respuesta', 'sugerencia', 'respuesta_sugerencia')


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

@admin.register(AvisoGlobal)
class AvisoGlobalAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'tipo', 'activo', 'fecha_creacion', 'total_vistos')
    list_filter = ('tipo', 'activo', 'fecha_creacion')
    search_fields = ('titulo', 'mensaje')
    readonly_fields = ('fecha_creacion',)
    exclude = ('visto_por',)

    def total_vistos(self, obj):
        return obj.visto_por.count()
    total_vistos.short_description = 'Vistos por'    