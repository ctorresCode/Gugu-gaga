from django.urls import include, path
from foro.views import InicioView, detalleHilo

urlpatterns = [
    path('', InicioView.as_view(), name='inicio'),
    path('detalle/<int:pk>/', detalleHilo.as_view(), name='detalle_hilo'),
]
