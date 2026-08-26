from django.urls import include, path
from foro.views import InicioView, boton_like, detalleHilo

urlpatterns = [
    path('', InicioView.as_view(), name='inicio'),
    path('detalle/<int:pk>/', detalleHilo.as_view(), name='detalle_hilo'),
    path('hilo/<int:hilo_id>/like/', boton_like, name='boton_like'),
]
