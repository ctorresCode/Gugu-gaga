from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from foro.models import Hilo, Universidad
from django.shortcuts import redirect, render

class InicioView(LoginRequiredMixin, TemplateView):
    template_name = 'foro/inicio.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        busqueda = self.request.GET.get('q', '')
        universidad_id = self.request.GET.get('uni', '')

        universidades = Universidad.objects.all()
        if busqueda:
            universidades = universidades.filter(nombre__icontains=busqueda)

        hilos = Hilo.objects.select_related('universidad', 'autor').filter(activo=True)
        
        if universidad_id and universidad_id.isdigit():
            hilos = hilos.filter(universidad_id=universidad_id)

        context['universidades'] = universidades
        context['hilos'] = hilos
        context['busqueda_actual'] = busqueda
        context['uni_actual'] = int(universidad_id) if universidad_id.isdigit() else ''

        return context

    def post(self, request, *args, **kwargs):
        contenido = request.POST.get('contenido')
        titulo = request.POST.get('titulo')
        imagen = request.FILES.get('imagen')

        if imagen:
            limite_tamano = 5 * 1024 * 1024
            if imagen.size > limite_tamano:
                return redirect(request.META.get('HTTP_REFERER', '/'))


        if contenido:
            nuevo_hilo = Hilo.objects.create(
                titulo=titulo,
                contenido=contenido,
                imagen=imagen if imagen else None,
                autor=request.user,
                universidad=getattr(request.user, 'universidad', None)
            )

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return render(request, 'foro/partials/tarjeta_hilo.html', {'hilo': nuevo_hilo})

        return redirect(request.META.get('HTTP_REFERER', '/'))

class detalleHilo(LoginRequiredMixin, DetailView):
    model = Hilo
    template_name = 'foro/detalle_hilo.html'
    context_object_name = 'hilo'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['respuestas'] = self.object.respuestas.filter(activo=True).select_related('autor')
        return context   

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        contenido = request.POST.get('contenido')

        if contenido:
            self.object.respuestas.create(
                contenido=contenido,
                autor=request.user
            ) 

        return redirect('detalle_hilo', pk=self.object.pk)    

