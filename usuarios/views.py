from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse, request
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q, Count
from django.core.cache import cache
from django.views.decorators.http import require_POST 
from django_ratelimit.decorators import ratelimit
from django.views.decorators.cache import never_cache
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from foro.models import Hilo
from usuarios.models import Mensaje, Universidad, UsuarioForo
from usuarios.forms import (
    RegistroForm, 
    SolicitarResetPasswordForm, 
    VerificarCodigoResetForm, 
    NuevaPasswordForm
)

class RegistroUsuarioView(CreateView):
    template_name = 'usuarios/registro.html'
    form_class = RegistroForm
    success_url = reverse_lazy('login')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        universidades = cache.get('universidades_list')
        if not universidades:
            universidades = Universidad.objects.all()
            cache.set('universidades_list', universidades, 86400)
        context['universidades'] = universidades
        return context

    def form_valid(self, form):
        usuario = form.save()
        login(self.request, usuario)
        return redirect('inicio')

def logout_view(request):
    logout(request)
    return render(request, 'usuarios/login.html')   

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
def seguir_usuario(request, username):
    with transaction.atomic():
        usuario_a_seguir = get_object_or_404(UsuarioForo.objects.select_for_update(), username=username)
        if request.user != usuario_a_seguir:
            if request.user.seguidos.filter(id=usuario_a_seguir.id).exists():
                request.user.seguidos.remove(usuario_a_seguir)
            else:
                request.user.seguidos.add(usuario_a_seguir)
    return redirect('perfil_usuario', username=username)

@login_required
def actualizar_avatar(request):
    if request.method == 'POST' and request.FILES.get('avatar'):
        avatar = request.FILES['avatar']
        if avatar.size > 2 * 1024 * 1024:
            return JsonResponse({'status': 'error', 'message': 'La imagen excede el límite de 2 MB.'}, status=400)

        request.user.avatar = avatar
        request.user.save()
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'}, status=400)

class BandejaMensajesView(LoginRequiredMixin, TemplateView):
    template_name = 'usuarios/mensajes.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['amigos'] = self.request.user.seguidos.filter(seguidos=self.request.user).annotate(
            mensajes_sin_leer=Count('mensajes_enviados', filter=Q(mensajes_enviados__destinatario=self.request.user, mensajes_enviados__leido=False))
        )
        return context

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
        otro_usuario = get_object_or_404(UsuarioForo, username=self.kwargs['username'])
        son_amigos = request.user.seguidos.filter(id=otro_usuario.id).exists() and otro_usuario.seguidos.filter(id=request.user.id).exists()

        if not son_amigos:
            return JsonResponse({'error': 'No tienen permisos para chatear.'}, status=403)

        contenido = request.POST.get('contenido')
        mensaje_respondido_id = request.POST.get('mensaje_respondido_id')
        
        mensaje_padre = None
        if mensaje_respondido_id:
            try:
                mensaje_padre = Mensaje.objects.get(id=mensaje_respondido_id)
            except Mensaje.DoesNotExist:
                mensaje_padre = None

        archivos_subidos = request.FILES.getlist('imagen')
        if len(archivos_subidos) > 4:
            return JsonResponse({'error': 'No puedes enviar más de 4 imágenes.'}, status=400)
            
        archivos = archivos_subidos[:4]

        limite_tamano = 5 * 1024 * 1024
        for archivo in archivos:
            if archivo.size > limite_tamano:
                return JsonResponse({'error': 'Una de las imágenes excede el límite de 5MB.'}, status=400)

        if contenido or archivos:
            nuevo_mensaje = Mensaje(
                remitente=request.user,
                destinatario=otro_usuario,
                contenido=contenido,
                mensaje_respondido=mensaje_padre
            )
            if len(archivos) > 0: nuevo_mensaje.imagen = archivos[0]
            if len(archivos) > 1: nuevo_mensaje.imagen2 = archivos[1]
            if len(archivos) > 2: nuevo_mensaje.imagen3 = archivos[2]
            if len(archivos) > 3: nuevo_mensaje.imagen4 = archivos[3]
            nuevo_mensaje.save()

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.headers.get('HX-Request'):
            return JsonResponse({'status': 'success'})

        return redirect('chat_usuario', username=otro_usuario.username)
        

class EditarPerfilView(LoginRequiredMixin, UpdateView):
    model = UsuarioForo
    fields = ['banner', 'avatar', 'username', 'descripcion', 'email']
    template_name = 'usuarios/editar_perfil.html'

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        avatar = self.request.FILES.get('avatar')
        banner = self.request.FILES.get('banner')
        limite_mb = 2 * 1024 * 1024 

        if avatar and avatar.size > limite_mb:
            form.add_error('avatar', 'El avatar no puede superar los 2MB.')
            return self.form_invalid(form)
        
        if banner and banner.size > limite_mb:
            form.add_error('banner', 'El banner no puede superar los 2MB.')
            return self.form_invalid(form)

        if avatar:
            form.instance.avatar = avatar
        if banner:
            form.instance.banner = banner
            
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('perfil_usuario', kwargs={'username': self.request.user.username})

class VerTodasLasImagenesSubidasPorUsuario(LoginRequiredMixin, ListView):
    model = Hilo
    template_name = 'usuarios/imagenes_subidas.html'
    context_object_name = 'imagenes_subidas'
    paginate_by = 20

    def get_queryset(self):
        return Hilo.objects.filter(
            autor__username=self.kwargs.get('username')
        ).select_related('autor', 'universidad').exclude(imagen='').exclude(imagen__isnull=True).order_by('-fecha_creacion')

@never_cache
@ratelimit(key='ip', rate='10/15m', method='POST', block=False)
def solicitar_reset_password(request):
    if request.user.is_authenticated:
        return redirect('inicio')

    form_email = SolicitarResetPasswordForm()
    form_codigo = VerificarCodigoResetForm()

    if request.method == 'POST':
        if getattr(request, 'limited', False):
            messages.error(request, 'Demasiados intentos. Espera unos minutos e inténtalo de nuevo.')
            
        elif request.POST.get('accion') == 'enviar_codigo':
            form_email = SolicitarResetPasswordForm(request.POST)
            if form_email.is_valid():
                email = form_email.cleaned_data['email']
                usuario = UsuarioForo.objects.filter(email__iexact=email, is_active=True).first()
                if usuario:
                    codigo = usuario.generar_codigo_reset_password()
                    send_mail(
                        subject='Tu código de recuperación - UniVoz',
                        message=(
                            f'Tu código de verificación es: {codigo}\n\n'
                            'Expira en 15 minutos. Si no solicitaste esto, ignora este correo.'
                        ),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[email],
                        fail_silently=True,
                    )
                    request.session['reset_usuario_id'] = usuario.id
                else:
                    request.session.pop('reset_usuario_id', None)
                
                request.session['reset_esperando'] = True
                messages.success(request, 'Si ese correo está registrado, te enviamos un código de verificación.')
                return redirect('recuperar_password')

        elif request.POST.get('accion') == 'verificar_codigo':
            if not request.session.get('reset_esperando'):
                messages.error(request, 'Tu sesión expiró, solicita el código de nuevo.')
                return redirect('recuperar_password')
                
            form_codigo = VerificarCodigoResetForm(request.POST)
            if form_codigo.is_valid():
                usuario_id = request.session.get('reset_usuario_id')
                usuario = UsuarioForo.objects.filter(id=usuario_id, is_active=True).first() if usuario_id else None
                
                if usuario and usuario.verificar_codigo_reset_password(form_codigo.cleaned_data['codigo']):
                    usuario.limpiar_codigo_reset_password()
                    request.session.pop('reset_usuario_id', None)
                    request.session.pop('reset_esperando', None)
                    request.session['reset_verificado_id'] = usuario.id
                    return redirect('nueva_password')
                
                messages.error(request, 'Código incorrecto o expirado.')

        elif request.POST.get('accion') == 'reenviar':
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
def nueva_password(request):
    usuario_id = request.session.get('reset_verificado_id')
    usuario = UsuarioForo.objects.filter(id=usuario_id, is_active=True).first() if usuario_id else None
    
    if not usuario:
        messages.error(request, 'Tu verificación expiró. Solicita el código de nuevo.')
        return redirect('recuperar_password')

    form = NuevaPasswordForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            validate_password(form.cleaned_data['password1'], usuario)
        except ValidationError as e:
            form.add_error('password1', e)
        else:
            usuario.set_password(form.cleaned_data['password1'])
            usuario.save(update_fields=['password'])
            request.session.pop('reset_verificado_id', None)
            login(request, usuario)
            messages.success(request, 'Tu contraseña fue cambiada correctamente.')
            return redirect('inicio') 

    return render(request, 'usuarios/nueva_password.html', {'form': form})

class TerminosView(TemplateView):
    template_name = 'usuarios/terminos.html'

class PrivacidadView(TemplateView):
    template_name = 'usuarios/privacidad.html'