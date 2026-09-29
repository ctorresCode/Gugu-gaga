from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from usuarios.models import MAX_DESCRIPCION, UsuarioForo, normalizar_email

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


class EditarPerfilForm(forms.ModelForm):
    # El email no se guarda directamente: si cambia, se envía un código a la nueva dirección
    # y solo se aplica al confirmarlo (ver EditarPerfilView / confirmar_email).
    email = forms.EmailField(required=False, label='Correo electrónico')
    descripcion = forms.CharField(required=False, max_length=MAX_DESCRIPCION, widget=forms.Textarea)

    class Meta:
        model = UsuarioForo
        fields = ['banner', 'avatar', 'username', 'descripcion']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].initial = self.instance.email

    def clean_email(self):
        email = normalizar_email(self.cleaned_data.get('email'))
        if email and UsuarioForo.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Ese correo ya está en uso.')
        return email

    def email_cambiado(self):
        return self.cleaned_data.get('email') != normalizar_email(self.instance.email)


class CodigoEmailForm(forms.Form):
    codigo = forms.CharField(
        label='Código de verificación',
        min_length=6,
        max_length=6,
        widget=forms.TextInput(attrs={'inputmode': 'numeric', 'autocomplete': 'one-time-code'})
    )
