from django.urls import include, path
from foro.views import EditarHilos, EliminarHilos, InicioView, Like_respuesta, SugerenciasCreateView, boton_like, detalle_respuesta, detalle_respuesta_sugerencia, detalle_sugerencia, detalleHilo, explorar_usuarios, interaccion_sugerencia, like_respuesta_sugerencia, notificaciones

urlpatterns = [
    path('', InicioView.as_view(), name='inicio'),
    path('detalle/<uuid:public_id>/', detalleHilo.as_view(), name='detalle_hilo'),
    path('hilo/<int:hilo_id>/like/', boton_like, name='boton_like'),

    path('hilo/<uuid:public_id>/editar/', EditarHilos.as_view(), name='editar_hilo'),
    path('hilo/<uuid:public_id>/eliminar/', EliminarHilos.as_view(), name='eliminar_hilo'),
    
    path('respuesta/<int:respuesta_id>/like/', Like_respuesta, name='like_respuesta'),
    path('respuesta/<uuid:public_id>/', detalle_respuesta, name='detalle_respuesta'),
    path('explorar/', explorar_usuarios, name='explorar'),
    path('notificaciones/', notificaciones, name='notificaciones'),
    path('sugerencias/', SugerenciasCreateView.as_view(), name='sugerencias'),
    path('sugerencias/<uuid:public_id>/', detalle_sugerencia, name='detalle_sugerencia'),
    path('sugerencias/<uuid:public_id>/<str:accion>/', interaccion_sugerencia, name='interaccion_sugerencia'),
    path('respuesta-sugerencia/<int:respuesta_id>/like/', like_respuesta_sugerencia, name='like_respuesta_sugerencia'),
    path('respuesta-sugerencia/<int:pk>/detalle/', detalle_respuesta_sugerencia, name='detalle_respuesta_sugerencia'),
]