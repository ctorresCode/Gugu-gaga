from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from usuarios.models import Mensaje, Universidad, UsuarioForo

@admin.register(UsuarioForo)
class UsuarioForoAdmin(UserAdmin):
    pass

@admin.register(Universidad)
class UniversidadAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'id')
    search_fields = ('nombre',)

@admin.register(Mensaje)
class MensajeAdmin(admin.ModelAdmin):
    list_display = ('remitente', 'destinatario', 'fecha_envio', 'leido')
    list_filter = ('leido', 'fecha_envio')
    search_fields = ('contenido',)
