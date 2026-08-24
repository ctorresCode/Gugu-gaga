from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin

from foro.models import Hilo
from usuarios.forms import RegistroForm
from usuarios.models import Universidad, UsuarioForo

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
    return render(request, 'usuarios/registro.html')   


class PerfilView(LoginRequiredMixin, DetailView):
    model = UsuarioForo
    template_name = 'usuarios/perfil.html'
    context_object_name = 'perfil_usuario'
    slug_field = 'username'
    slug_url_kwarg = 'username'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['hilos_usuario'] = Hilo.objects.filter(autor=self.object, activo=True).select_related('universidad', 'autor')
        return context

@login_required
def actualizar_avatar(request):
    if request.method == 'POST' and request.FILES.get('avatar'):
        user = request.user
        user.avatar = request.FILES['avatar']
        user.save()
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'}, status=400)
