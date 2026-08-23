from django.contrib import admin

from usuarios.models import Universidad, UsuarioForo

# Register your models here.
admin.site.register(UsuarioForo)
admin.site.register(Universidad)
