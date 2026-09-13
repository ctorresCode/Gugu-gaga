
import os
from django.contrib import admin
from django.conf.urls.static import static
from django.urls import include, path, re_path
from django.views.static import serve

from config import settings

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('foro.urls')),
    path('', include('usuarios.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static('/hilos/imagenes/', document_root=os.path.join(settings.BASE_DIR, 'hilos/imagenes'))
else:
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
        re_path(r'^hilos/imagenes/(?P<path>.*)$', serve, {'document_root': os.path.join(settings.BASE_DIR, 'hilos/imagenes')}),
    ]
       
