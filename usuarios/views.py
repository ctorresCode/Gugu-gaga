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
from usuarios.forms import RegistroForm, RecuperarPasswordForm
from django_ratelimit.decorators import ratelimit
from django.views.decorators.cache import never_cache
from foro.models import Hilo
from foro.views import ImagenInvalidaError, comprimir_y_optimizar_imagen
from usuarios.forms import RegistroForm
from usuarios.models import Mensaje, Universidad, UsuarioForo

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
        codigo = usuario.generar_codigo_recuperacion()
        login(self.request, usuario)
        self.request.session['codigo_recuperacion_nuevo'] = codigo
        return redirect('codigo_recuperacion')
        #return super().form_valid(form)

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

        try:
            avatar_optimizado = comprimir_y_optimizar_imagen(avatar, max_ancho=500, calidad=80)
        except ImagenInvalidaError as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
           
        request.user.avatar = avatar_optimizado
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

        archivos_optimizados = []
        for archivo in archivos:
            try:
                archivos_optimizados.append(comprimir_y_optimizar_imagen(archivo, max_ancho=1200, calidad=80))
            except ImagenInvalidaError as e:
                return JsonResponse({'error': str(e)}, status=400)

        if contenido or archivos_optimizados:
            nuevo_mensaje = Mensaje(
                remitente=request.user,
                destinatario=otro_usuario,
                contenido=contenido,
                mensaje_respondido=mensaje_padre
            )
            if len(archivos_optimizados) > 0: nuevo_mensaje.imagen = archivos_optimizados[0]
            if len(archivos_optimizados) > 1: nuevo_mensaje.imagen2 = archivos_optimizados[1]
            if len(archivos_optimizados) > 2: nuevo_mensaje.imagen3 = archivos_optimizados[2]
            if len(archivos_optimizados) > 3: nuevo_mensaje.imagen4 = archivos_optimizados[3]
            nuevo_mensaje.save()

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.headers.get('HX-Request'):
            return JsonResponse({'status': 'success'})

        return redirect('chat_usuario', username=otro_usuario.username)
        

class EditarPerfilView(LoginRequiredMixin, UpdateView):
    model = UsuarioForo
    fields = ['banner', 'avatar', 'username', 'descripcion']
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
            try:
                form.instance.avatar = comprimir_y_optimizar_imagen(avatar, max_ancho=500, calidad=80)
            except ImagenInvalidaError as e:    
                form.add_error('avatar', str(e))
                return self.form_invalid(form)

        if banner:
            try:
                form.instance.banner = comprimir_y_optimizar_imagen(banner, max_ancho=1200, calidad=85)
            except ImagenInvalidaError as e:
                form.add_error('banner', str(e))
                return self.form_invalid(form)    
            
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
@ratelimit(key='post:username', rate='5/15m', method='POST', block=False)
@ratelimit(key='ip', rate='20/h', method='POST', block=False)
def recuperar_password(request):
    if request.user.is_authenticated:
        return redirect('inicio')

    if request.method == 'POST':
        if getattr(request, 'limited', False):
            messages.error(request, 'Demasiados intentos. Espera unos minutos e inténtalo de nuevo.')
            form = RecuperarPasswordForm()
        else:
            form = RecuperarPasswordForm(request.POST)
            if form.is_valid():
                usuario = form.save()
                codigo_nuevo = usuario.generar_codigo_recuperacion()
                login(request, usuario)
                request.session['codigo_recuperacion_nuevo'] = codigo_nuevo
                messages.success(request, 'Tu contraseña fue cambiada. Guarda tu nuevo código.')
                return redirect('codigo_recuperacion')
    else:
        form = RecuperarPasswordForm()

    return render(request, 'usuarios/recuperar_password.html', {'form': form})


@login_required
@never_cache
def codigo_recuperacion(request):
    codigo = request.session.pop('codigo_recuperacion_nuevo', None)

    if request.method == 'POST' and not codigo:
        if request.user.check_password(request.POST.get('password', '')):
            codigo = request.user.generar_codigo_recuperacion()
        else:
            messages.error(request, 'Contraseña incorrecta.')

    return render(request, 'usuarios/codigo_recuperacion.html', {'codigo': codigo})


class TerminosView(TemplateView):
    template_name = 'usuarios/terminos.html'

class PrivacidadView(TemplateView):
    template_name = 'usuarios/privacidad.html'    