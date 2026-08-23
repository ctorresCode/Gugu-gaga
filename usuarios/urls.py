from django.urls import include, path
from django.contrib.auth.views import LoginView, LogoutView

from usuarios.views import RegistroUsuarioView

urlpatterns = [
    path('registro/', RegistroUsuarioView.as_view(), name='registro' ),
    path('login/', LoginView.as_view(template_name='usuarios/login.html'), name='login' ),
    path('logout/', LogoutView.as_view(), name='logout' ),
]
