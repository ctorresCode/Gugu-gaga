
from django import forms
from usuarios.models import UsuarioForo
from django.contrib.auth.forms import UserCreationForm

class RegistroForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = UsuarioForo
        fields = ['username', 'universidad']






