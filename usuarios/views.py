from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, TemplateView
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q, Count

from foro.models import Hilo
from usuarios.forms import RegistroForm
from usuarios.models import Mensaje, Universidad, UsuarioForo

# Create your views here.
class RegistroUsuarioView(CreateView):
    template_name = 'usuarios/registro.html'
    form_class = RegistroForm
    success_url = reverse_lazy('login')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['universidades'] = Universidad.objects.all()
        return context

    def form_valid(self, form):
        usuario = form.save()
        login(self.request, usuario)
        return super().form_valid(form)

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
        context['hilos_usuario'] = Hilo.objects.filter(autor=self.object, activo=True).select_related('universidad', 'autor')

        if self.request.user.is_authenticated:
            context['lo_sigo'] = self.request.user.seguidos.filter(id=self.object.id).exists()

        return context


@login_required
def seguir_usuario(request, username):
    usuario_a_seguir = get_object_or_404(UsuarioForo, username=username)
    
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
        
        limite_avatar = 2 * 1024 * 1024
        if avatar.size > limite_avatar:
            return JsonResponse({'status': 'error', 'message': 'La imagen excede el límite de 2 MB.'}, status=400)

        user = request.user
        user.avatar = avatar
        user.save()
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
        
        mensajes = Mensaje.objects.filter(
            (Q(remitente=self.request.user) & Q(destinatario=otro_usuario)) |
            (Q(remitente=otro_usuario) & Q(destinatario=self.request.user))
        ).order_by('fecha_envio')
        
        context['mensajes'] = mensajes
        return context

    def post(self, request, *args, **kwargs):
        otro_usuario = get_object_or_404(UsuarioForo, username=self.kwargs['username'])
        
        son_amigos = request.user.seguidos.filter(id=otro_usuario.id).exists() and otro_usuario.seguidos.filter(id=request.user.id).exists()
        
        if not son_amigos:
            return redirect('bandeja_mensajes')
            
        contenido = request.POST.get('contenido')
        
        if contenido:
            Mensaje.objects.create(
                remitente=request.user,
                destinatario=otro_usuario,
                contenido=contenido
            )
        return redirect('chat_usuario', username=otro_usuario.username)
