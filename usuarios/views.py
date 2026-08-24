from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.generic import CreateView
from django.contrib.auth import login, logout

from usuarios.forms import RegistroForm
from usuarios.models import Universidad

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

    
