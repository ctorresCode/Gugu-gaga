from django.urls import include, path
from foro.views import InicioView, Like_respuesta, boton_like, detalle_respuesta, detalleHilo, explorar_usuarios, notificaciones

urlpatterns = [
    path('', InicioView.as_view(), name='inicio'),
    path('detalle/<int:pk>/', detalleHilo.as_view(), name='detalle_hilo'),
    path('hilo/<int:hilo_id>/like/', boton_like, name='boton_like'),
    path('respuesta/<int:respuesta_id>/like/',Like_respuesta, name='like_respuesta'),
    path('respuesta/<int:pk>/', detalle_respuesta, name='detalle_respuesta'),
    path('explorar/', explorar_usuarios, name='explorar'),
    path('notificaciones/', notificaciones, name='notificaciones'),
]
