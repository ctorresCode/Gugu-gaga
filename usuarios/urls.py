from django.urls import include, path
from django.contrib.auth.views import LoginView, LogoutView

from usuarios.views import (
    EditarPerfilView,
    PerfilView, 
    RegistroUsuarioView, 
    actualizar_avatar, 
    logout_view, 
    seguir_usuario, 
    BandejaMensajesView, 
    ChatView
)

urlpatterns = [
    path('registro/', RegistroUsuarioView.as_view(), name='registro' ),
    path('login/', LoginView.as_view(template_name='usuarios/login.html'), name='login' ),
    path('logout/', logout_view, name='logout' ),

    #urls del perfil del usuario
    path('perfil/actualizar-avatar/', actualizar_avatar, name='actualizar_avatar'),
    path('perfil/<str:username>/', PerfilView.as_view(), name='perfil_usuario'),
    path('perfil/<str:username>/seguir/', seguir_usuario, name='seguir_usuario'),
    path('editar-perfil/<str:username>/', EditarPerfilView.as_view(), name='editar_perfil'),

    #urls para el lanzamiento y recibimiento de mensajes
    path('mensajes/', BandejaMensajesView.as_view(), name='bandeja_mensajes'),
    path('mensajes/<str:username>/', ChatView.as_view(), name='chat_usuario'),
]
