
import os

from django.contrib import admin
from django.conf.urls.static import static
from django.urls import include, path

from config import settings

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('foro.urls')),
    path('', include('usuarios.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static('/hilos/imagenes/', document_root=os.path.join(settings.BASE_DIR, 'hilos/imagenes'))
