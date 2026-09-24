from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from usuarios.models import UsuarioForo

VERSION_TERMINOS = '2026-09'


class RegistroForm(UserCreationForm):
    mayor_edad = forms.BooleanField(
        required=True,
        label="Confirmo que tengo 18 años o más."
    )
    consentimiento = forms.BooleanField(required=True)

    class Meta(UserCreationForm.Meta):
        model = UsuarioForo
        fields = ['username', 'email', 'universidad']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].label = 'Correo electrónico (para recuperar tu contraseña)'
        self.fields['consentimiento'].label = format_html(
            'He leído y acepto los <a href="{}" target="_blank" class="underline font-semibold">Términos y Condiciones</a> '
            'y la <a href="{}" target="_blank" class="underline font-semibold">Política de Privacidad</a>. '
            'Entiendo que soy responsable de lo que publique y que el contenido que infrinja las reglas puede ser eliminado.',
            reverse('terminos'), reverse('privacidad'),
        )

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if not email:
            return None
        if UsuarioForo.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Ese correo ya está registrado.')
        return email

    def save(self, commit=True):
        self.instance.acepto_terminos_fecha = timezone.now()
        self.instance.acepto_terminos_version = VERSION_TERMINOS

        if not self.instance.email:
            self.instance.email = None

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
