
from django import forms
from usuarios.models import UsuarioForo, normalizar_codigo
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

class RegistroForm(UserCreationForm):
    consentimiento = forms.BooleanField(
        required=True,
        label="Entiendo y acepto que soy totalmente responsable de lo que publique de forma anónima."
    )

    class Meta(UserCreationForm.Meta):
        model = UsuarioForo
        fields = ['username', 'universidad']

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







