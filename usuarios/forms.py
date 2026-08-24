
from django import forms
from usuarios.models import UsuarioForo
from django.contrib.auth.forms import UserCreationForm

class RegistroForm(UserCreationForm):
    consentimiento = forms.BooleanField(
        required=True,
        label="Entiendo y acepto que soy totalmente responsable de lo que publique de forma anónima."
    )

    class Meta(UserCreationForm.Meta):
        model = UsuarioForo
        fields = ['username', 'universidad']






