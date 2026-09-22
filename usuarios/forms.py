
from django import forms
from usuarios.models import UsuarioForo, normalizar_codigo
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.html import format_html
from django.utils import timezone

VERSION_TERMINOS = '2026-09'

class RegistroForm(UserCreationForm):
    mayor_edad = forms.BooleanField(
        required=True,
        label="Confirmo que tengo 18 años o más."
    )
    consentimiento = forms.BooleanField(required=True)

    class Meta(UserCreationForm.Meta):
        model = UsuarioForo
        fields = ['username', 'universidad']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['consentimiento'].label = format_html(
            'He leído y acepto los <a href="{}" target="_blank" class="underline font-semibold">Términos y Condiciones</a> '
            'y la <a href="{}" target="_blank" class="underline font-semibold">Política de Privacidad</a>. '
            'Entiendo que soy responsable de lo que publique y que el contenido que infrinja las reglas puede ser eliminado.',
            reverse('terminos'), reverse('privacidad'),
        )

    def save(self, commit=True):
        self.instance.acepto_terminos_fecha = timezone.now()
        self.instance.acepto_terminos_version = VERSION_TERMINOS
        return super().save(commit=commit)    

class SolicitarResetPasswordForm(forms.Form):
    email = forms.EmailField(label='Correo electrónico')

class VerificarCodigoResetForm(forms.Form):
    codigo = forms.CharField(
        label='Código de verificación',
        min_length=6,
        max_length=6,
        widget=forms.TextInput(attrs={'inputmode': 'numeric', 'autocomplete': 'one-time-code'})
    )

class NuevaPasswordForm(forms.Form):
    password1 = forms.CharField(widget=forms.PasswordInput, label='Nueva contraseña')
    password2 = forms.CharField(widget=forms.PasswordInput, label='Repite la contraseña')

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get('password1'), cleaned.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', 'Las contraseñas no coinciden.')
        return cleaned


def clean_contenido(self):
    contenido = self.cleaned_data.get('contenido', '').strip()
    if len(contenido) > 500:
        raise forms.ValidationError('El contenido no puede superar los 500 caracteres.')
    if not contenido:
        raise forms.ValidationError('El contenido no puede estar vacío.')
    return contenido




