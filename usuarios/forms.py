
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


class RecuperarPasswordForm(forms.Form):
    username = forms.CharField(max_length=150, label='Username')
    codigo = forms.CharField(max_length=32, label='Código de recuperación')
    password1 = forms.CharField(widget=forms.PasswordInput, label='Nueva contraseña')
    password2 = forms.CharField(widget=forms.PasswordInput, label='Repite la contraseña')

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned

        p1, p2 = cleaned['password1'], cleaned['password2']
        if p1 != p2:
            self.add_error('password2', 'Las contraseñas no coinciden.')
            return cleaned

        usuario = UsuarioForo.objects.filter(username=cleaned['username'], is_active=True).first()
        if usuario:
            valido = usuario.verificar_codigo_recuperacion(cleaned['codigo'])
        else:
            make_password(normalizar_codigo(cleaned['codigo']))  # mismo costo de tiempo, no revela si el usuario existe
            valido = False

        if not valido:
            raise ValidationError('Usuario o código de recuperación incorrectos.')

        try:
            validate_password(p1, usuario)
        except ValidationError as e:
            self.add_error('password1', e)
            return cleaned

        self.usuario = usuario
        return cleaned

    def save(self):
        self.usuario.set_password(self.cleaned_data['password1'])
        self.usuario.save(update_fields=['password'])
        return self.usuario







