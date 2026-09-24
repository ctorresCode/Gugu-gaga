import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView
from django_ratelimit.core import is_ratelimited
from django_ratelimit.decorators import ratelimit

from config.utils import ip_key
from foro.limites import (
    limite_chat,
    limite_excedido,
    limite_perfil,
    limite_registro,
    limite_seguir,
)
from foro.models import Hilo
from foro.utils import MAX_MENSAJE, a_int, limpiar_texto, procesar_imagenes
from usuarios.forms import (
    NuevaPasswordForm,
    RegistroForm,
    SolicitarResetPasswordForm,
    VerificarCodigoResetForm,
)
from usuarios.models import Mensaje, Universidad, UsuarioForo

logger = logging.getLogger(__name__)

RESET_VERIFICACION_SEGUNDOS = 10 * 60  
CLAVES_SESION_RESET = ('reset_usuario_id', 'reset_esperando', 'reset_verificado_id', 'reset_verificado_en')

@method_decorator(limite_registro, name='post')
class RegistroUsuarioView(CreateView):
    template_name = 'usuarios/registro.html'
    form_class = RegistroForm
    success_url = reverse_lazy('login')

    def post(self, request, *args, **kwargs):
        if getattr(request, 'limited', False):
            messages.error(request, 'Demasiados registros desde esta red. Intenta más tarde.')
            return redirect(request.path)
        return super().post(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        universidades = cache.get('universidades_list')
        if not universidades:
            universidades = Universidad.objects.all()
            cache.set('universidades_list', universidades, 86400)
        context['universidades'] = universidades
        return context

    def form_valid(self, form):
        form.save()
        return redirect('login')


def logout_view(request):
    logout(request)
    return redirect('login')


class PerfilView(LoginRequiredMixin, DetailView):
    model = UsuarioForo
    template_name = 'usuarios/perfil.html'
    context_object_name = 'perfil_usuario'
    slug_field = 'username'
    slug_url_kwarg = 'username'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['hilos_usuario'] = Hilo.objects.filter(
            autor=self.object, activo=True
        ).select_related('universidad', 'autor').annotate(
            conteo_likes=Count('likes', distinct=True),
            conteo_respuestas=Count('respuestas', filter=Q(respuestas__activo=True), distinct=True)
        )[:50]

        if self.request.user.is_authenticated:
            context['lo_sigo'] = self.request.user.seguidos.filter(id=self.object.id).exists()
        return context


@login_required
@require_POST
@limite_seguir
def seguir_usuario(request, username):
    destino = reverse('perfil_usuario', kwargs={'username': username})

    if getattr(request, 'limited', False):
        return limite_excedido(request, 'Estás siguiendo usuarios muy rápido. Espera un momento.', destino)

    with transaction.atomic():
        usuario_a_seguir = get_object_or_404(UsuarioForo.objects.select_for_update(), username=username)
        if request.user != usuario_a_seguir:
            if request.user.seguidos.filter(id=usuario_a_seguir.id).exists():
                request.user.seguidos.remove(usuario_a_seguir)
            else:
                request.user.seguidos.add(usuario_a_seguir)
    return redirect(destino)

@login_required
@require_POST
@limite_perfil
def actualizar_avatar(request):
    if getattr(request, 'limited', False):
        return JsonResponse(
            {'status': 'error', 'message': 'Has cambiado tu avatar muchas veces. Intenta más tarde.'}, status=429
        )

    archivo = request.FILES.get('avatar')
    if not archivo:
        return JsonResponse({'status': 'error', 'message': 'No se recibió ninguna imagen.'}, status=400)

    limpios, error = procesar_imagenes([archivo], max_mb=2)
    if error:
        return JsonResponse({'status': 'error', 'message': error}, status=400)

    request.user.avatar = limpios[0]
    request.user.save(update_fields=['avatar'])
    return JsonResponse({'status': 'success'})


@method_decorator(limite_perfil, name='post')
class EditarPerfilView(LoginRequiredMixin, UpdateView):
    model = UsuarioForo
    fields = ['banner', 'avatar', 'username', 'descripcion', 'email']
    template_name = 'usuarios/editar_perfil.html'

    def get_object(self, queryset=None):
        return self.request.user

    def post(self, request, *args, **kwargs):
        if getattr(request, 'limited', False):
            messages.error(request, 'Has editado tu perfil muchas veces. Intenta de nuevo más tarde.')
            return redirect(request.path)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        for campo in ('avatar', 'banner'):
            archivo = self.request.FILES.get(campo)
            if archivo:
                limpios, error = procesar_imagenes([archivo], max_mb=2)
                if error:
                    form.add_error(campo, error)
                    return self.form_invalid(form)
                setattr(form.instance, campo, limpios[0])

        email = form.cleaned_data.get('email')
        if email:
            email = email.strip().lower()
            if UsuarioForo.objects.filter(email__iexact=email).exclude(pk=self.request.user.pk).exists():
                form.add_error('email', 'Ese correo ya está en uso.')
                return self.form_invalid(form)
        form.instance.email = email or None

        return super().form_valid(form)

    def get_success_url(self):
        return reverse('perfil_usuario', kwargs={'username': self.request.user.username})


class VerTodasLasImagenesSubidasPorUsuario(LoginRequiredMixin, ListView):
    model = Hilo
    template_name = 'usuarios/imagenes_subidas.html'
    context_object_name = 'imagenes_subidas'
    paginate_by = 20

    def get_queryset(self):
        return Hilo.objects.filter(
            autor__username=self.kwargs.get('username'), activo=True
        ).select_related('autor', 'universidad').exclude(imagen='').exclude(imagen__isnull=True).order_by('-fecha_creacion')

class BandejaMensajesView(LoginRequiredMixin, TemplateView):
    template_name = 'usuarios/mensajes.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['amigos'] = self.request.user.seguidos.filter(seguidos=self.request.user).annotate(
            mensajes_sin_leer=Count('mensajes_enviados', filter=Q(mensajes_enviados__destinatario=self.request.user, mensajes_enviados__leido=False))
        )
        return context


@method_decorator(limite_chat, name='post')
class ChatView(LoginRequiredMixin, TemplateView):
    template_name = 'usuarios/mensajes.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        otro_usuario = get_object_or_404(UsuarioForo, username=self.kwargs['username'])

        Mensaje.objects.filter(remitente=otro_usuario, destinatario=self.request.user, leido=False).update(leido=True)

        context['amigos'] = self.request.user.seguidos.filter(seguidos=self.request.user).annotate(
            mensajes_sin_leer=Count('mensajes_enviados', filter=Q(mensajes_enviados__destinatario=self.request.user, mensajes_enviados__leido=False))
        )
        context['chat_activo'] = otro_usuario

        mensajes_query = Mensaje.objects.filter(
            (Q(remitente=self.request.user, destinatario=otro_usuario)) |
            (Q(remitente=otro_usuario, destinatario=self.request.user))
        ).select_related('remitente', 'mensaje_respondido', 'mensaje_respondido__remitente').order_by('-fecha_envio')[:50]

        context['mensajes'] = reversed(list(mensajes_query))
        return context

    def post(self, request, *args, **kwargs):
        if getattr(request, 'limited', False):
            return JsonResponse({'error': 'Estás enviando mensajes muy rápido. Espera un momento.'}, status=429)

        otro_usuario = get_object_or_404(UsuarioForo, username=self.kwargs['username'])
        son_amigos = request.user.seguidos.filter(id=otro_usuario.id).exists() and otro_usuario.seguidos.filter(id=request.user.id).exists()

        if not son_amigos:
            return JsonResponse({'error': 'No tienen permisos para chatear.'}, status=403)

        contenido, error = limpiar_texto(
            request.POST.get('contenido'), MAX_MENSAJE, requerido=False, nombre='El mensaje'
        )
        if error:
            return JsonResponse({'error': error}, status=400)

        mensaje_padre = None
        mensaje_respondido_id = a_int(request.POST.get('mensaje_respondido_id'))
        if mensaje_respondido_id:
            mensaje_padre = Mensaje.objects.filter(
                Q(remitente=request.user, destinatario=otro_usuario) |
                Q(remitente=otro_usuario, destinatario=request.user),
                id=mensaje_respondido_id,
            ).first()

        archivos_subidos = request.FILES.getlist('imagen')
        if len(archivos_subidos) > 4:
            return JsonResponse({'error': 'No puedes enviar más de 4 imágenes.'}, status=400)

        if archivos_subidos and is_ratelimited(
            request, group='chat_imagenes', key='user', rate='10/m', method='POST', increment=True
        ):
            return JsonResponse({'error': 'Estás enviando imágenes muy rápido. Espera un momento.'}, status=429)

        archivos, error = procesar_imagenes(archivos_subidos, max_mb=5)
        if error:
            return JsonResponse({'error': error}, status=400)

        if not contenido and not archivos:
            return JsonResponse({'error': 'El mensaje está vacío.'}, status=400)

        nuevo_mensaje = Mensaje(
            remitente=request.user,
            destinatario=otro_usuario,
            contenido=contenido or None,
            mensaje_respondido=mensaje_padre
        )
        for campo, archivo in zip(('imagen', 'imagen2', 'imagen3', 'imagen4'), archivos):
            setattr(nuevo_mensaje, campo, archivo)
        nuevo_mensaje.save()

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.headers.get('HX-Request'):
            return JsonResponse({'status': 'success'})

        return redirect('chat_usuario', username=otro_usuario.username)


def key_email(group, request):
    return (request.POST.get('email') or '').strip().lower() or 'sin-email'


def _limpiar_sesion_reset(request):
    for clave in CLAVES_SESION_RESET:
        request.session.pop(clave, None)


def _usuario_verificado_reset(request):
    usuario_id = request.session.get('reset_verificado_id')
    verificado_en = request.session.get('reset_verificado_en')
    if not usuario_id or not verificado_en:
        return None
    if timezone.now().timestamp() - verificado_en > RESET_VERIFICACION_SEGUNDOS:
        return None
    return UsuarioForo.objects.filter(id=usuario_id, is_active=True).first()


@never_cache
def solicitar_reset_password(request):
    if request.user.is_authenticated:
        return redirect('inicio')

    form_email = SolicitarResetPasswordForm()
    form_codigo = VerificarCodigoResetForm()

    if request.method == 'POST':
        accion = request.POST.get('accion')

        if accion == 'enviar_codigo':
            form_email = SolicitarResetPasswordForm(request.POST)
            if form_email.is_valid():
                email = form_email.cleaned_data['email'].strip().lower()

                if (
                    is_ratelimited(request, group='reset_ip', key=ip_key, rate='30/h', method='POST', increment=True)
                    or is_ratelimited(request, group='reset_email', key=key_email, rate='3/h', method='POST', increment=True)
                ):
                    messages.error(request, 'Demasiados intentos. Espera unos minutos e inténtalo de nuevo.')
                else:
                    usuario = UsuarioForo.objects.filter(email__iexact=email, is_active=True).first()
                    if usuario:
                        if usuario.puede_pedir_codigo_reset():
                            codigo = usuario.generar_codigo_reset_password()
                            try:
                                send_mail(
                                    subject='Tu código de recuperación - UniVoz',
                                    message=(
                                        f'Tu código de verificación es: {codigo}\n\n'
                                        'Expira en 15 minutos. Si no solicitaste esto, ignora este correo.'
                                    ),
                                    from_email=settings.DEFAULT_FROM_EMAIL,
                                    recipient_list=[email],
                                    fail_silently=False,
                                )
                            except Exception:
                                logger.exception('No se pudo enviar el correo de reset (usuario %s)', usuario.id)
                        request.session['reset_usuario_id'] = usuario.id
                    else:
                        request.session.pop('reset_usuario_id', None)

                    request.session['reset_esperando'] = True
                    messages.success(request, 'Si ese correo está registrado, te enviamos un código de verificación.')
                    return redirect('recuperar_password')

        elif accion == 'verificar_codigo':
            if not request.session.get('reset_esperando'):
                messages.error(request, 'Tu sesión expiró, solicita el código de nuevo.')
                return redirect('recuperar_password')

            form_codigo = VerificarCodigoResetForm(request.POST)
            if is_ratelimited(request, group='reset_verificar', key=ip_key, rate='30/h', method='POST', increment=True):
                messages.error(request, 'Demasiados intentos. Espera unos minutos e inténtalo de nuevo.')
            elif form_codigo.is_valid():
                usuario_id = request.session.get('reset_usuario_id')
                usuario = UsuarioForo.objects.filter(id=usuario_id, is_active=True).first() if usuario_id else None

                if usuario and usuario.verificar_codigo_reset_password(form_codigo.cleaned_data['codigo']):
                    usuario.limpiar_codigo_reset_password()
                    request.session.pop('reset_usuario_id', None)
                    request.session.pop('reset_esperando', None)
                    request.session['reset_verificado_id'] = usuario.id
                    request.session['reset_verificado_en'] = timezone.now().timestamp()
                    return redirect('nueva_password')

                messages.error(request, 'Código incorrecto o expirado.')

        elif accion == 'reenviar':
            request.session.pop('reset_usuario_id', None)
            request.session.pop('reset_esperando', None)
            return redirect('recuperar_password')

    esperando_codigo = request.session.get('reset_esperando', False)
    return render(request, 'usuarios/solicitar_reset.html', {
        'form_email': form_email,
        'form_codigo': form_codigo,
        'esperando_codigo': esperando_codigo,
    })


@never_cache
@ratelimit(key=ip_key, group='nueva_password', rate='10/h', method='POST', block=False)
def nueva_password(request):
    usuario = _usuario_verificado_reset(request)

    if not usuario:
        _limpiar_sesion_reset(request)
        messages.error(request, 'Tu verificación expiró. Solicita el código de nuevo.')
        return redirect('recuperar_password')

    form = NuevaPasswordForm(request.POST or None)
    if request.method == 'POST':
        if getattr(request, 'limited', False):
            messages.error(request, 'Demasiados intentos. Espera unos minutos e inténtalo de nuevo.')
        elif form.is_valid():
            try:
                validate_password(form.cleaned_data['password1'], usuario)
            except ValidationError as e:
                form.add_error('password1', e)
            else:
                usuario.set_password(form.cleaned_data['password1'])
                usuario.save(update_fields=['password'])
                _limpiar_sesion_reset(request)
                login(request, usuario, backend='django.contrib.auth.backends.ModelBackend')
                messages.success(request, 'Tu contraseña fue cambiada correctamente.')
                return redirect('inicio')

    return render(request, 'usuarios/nueva_password.html', {'form': form})


class TerminosView(TemplateView):
    template_name = 'usuarios/terminos.html'


class PrivacidadView(TemplateView):
    template_name = 'usuarios/privacidad.html'
