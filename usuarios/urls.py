from django.urls import include, path
from django.contrib.auth.views import LoginView, LogoutView

from usuarios.views import PerfilView, RegistroUsuarioView, actualizar_avatar, logout_view

urlpatterns = [
    path('registro/', RegistroUsuarioView.as_view(), name='registro' ),
    path('login/', LoginView.as_view(template_name='usuarios/login.html'), name='login' ),
    path('logout/', logout_view, name='logout' ),

    #urls del perfil del usuario
    path('perfil/actualizar-avatar/', actualizar_avatar, name='actualizar_avatar'),
    path('perfil/<str:username>/', PerfilView.as_view(), name='perfil_usuario'),
]
