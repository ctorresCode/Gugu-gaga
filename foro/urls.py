from django.urls import include, path
from foro.views import InicioView, Like_respuesta, SugerenciasCreateView, boton_like, detalle_respuesta, detalle_respuesta_sugerencia, detalle_sugerencia, detalleHilo, explorar_usuarios, interaccion_sugerencia, like_respuesta_sugerencia, notificaciones

urlpatterns = [
    path('', InicioView.as_view(), name='inicio'),
    path('detalle/<int:pk>/', detalleHilo.as_view(), name='detalle_hilo'),
    path('hilo/<int:hilo_id>/like/', boton_like, name='boton_like'),
    path('respuesta/<int:respuesta_id>/like/', Like_respuesta, name='like_respuesta'),
    path('respuesta/<int:pk>/', detalle_respuesta, name='detalle_respuesta'),
    path('explorar/', explorar_usuarios, name='explorar'),
    path('notificaciones/', notificaciones, name='notificaciones'),
    path('sugerencias/', SugerenciasCreateView.as_view(), name='sugerencias'),
    path('sugerencias/<int:pk>/', detalle_sugerencia, name='detalle_sugerencia'),
    path('sugerencias/<int:pk>/<str:accion>/', interaccion_sugerencia, name='interaccion_sugerencia'),
    path('respuesta-sugerencia/<int:respuesta_id>/like/', like_respuesta_sugerencia, name='like_respuesta_sugerencia'),
    path('respuesta-sugerencia/<int:pk>/detalle/', detalle_respuesta_sugerencia, name='detalle_respuesta_sugerencia'),
]