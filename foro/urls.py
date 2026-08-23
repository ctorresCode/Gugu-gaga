from django.urls import include, path

from foro.views import InicioView

urlpatterns = [
    path('', InicioView.as_view(), name='inicio'),
]
