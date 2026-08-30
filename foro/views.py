from django.core.cache import cache
from django.db.models import Q, Count
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from foro.models import Hilo, Respuesta, Universidad
from django.shortcuts import redirect, render, get_object_or_404
from django.contrib.auth.decorators import login_required

from usuarios.models import UsuarioForo

class InicioView(LoginRequiredMixin, TemplateView):
    template_name = 'foro/inicio.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        busqueda = self.request.GET.get('q', '')
        universidad_id = self.request.GET.get('uni', '')

        universidades = cache.get('universidades_list')
        if not universidades:
            universidades = Universidad.objects.all()
            cache.set('universidades_list', universidades, 86400)
            
        if busqueda:
            universidades = universidades.filter(nombre__icontains=busqueda)

        hilos = Hilo.objects.select_related('universidad', 'autor').filter(activo=True)
        
        if universidad_id and universidad_id.isdigit():
            hilos = hilos.filter(universidad_id=universidad_id)

        hilos = hilos.annotate(
            conteo_likes=Count('likes', distinct=True),
            conteo_respuestas=Count('respuestas', filter=Q(respuestas__activo=True), distinct=True)
        ).order_by('-fecha_creacion')[:50]

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

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('HX-Request'):
                return render(request, 'foro/partials/tarjeta_hilo.html', {'hilo': nuevo_hilo})

        return redirect(request.META.get('HTTP_REFERER', '/'))

class detalleHilo(LoginRequiredMixin, DetailView):
    model = Hilo
    template_name = 'foro/detalle_hilo.html'
    context_object_name = 'hilo'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['respuestas'] = self.object.respuestas.filter(
            activo=True, respuesta_padre__isnull=True
        ).select_related('autor').annotate(
            conteo_likes=Count('likes', distinct=True),
            conteo_respuestas_hijas=Count('respuestas_hijas', filter=Q(respuestas_hijas__activo=True), distinct=True)
        ).order_by('fecha_creacion')
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

@login_required
def detalle_respuesta(request, pk):
    respuesta_actual = get_object_or_404(Respuesta, pk=pk)
    hilo_original = respuesta_actual.hilo
    
    if request.method == 'POST':
        contenido = request.POST.get('contenido')
        if contenido:
            Respuesta.objects.create(
                autor=request.user,
                hilo=hilo_original,
                respuesta_padre=respuesta_actual,
                contenido=contenido
            )
            return redirect('detalle_respuesta', pk=respuesta_actual.pk)

    respuestas_hijas = respuesta_actual.respuestas_hijas.filter(activo=True).select_related('autor').annotate(
        conteo_likes=Count('likes', distinct=True)
    ).order_by('fecha_creacion')

    return render(request, 'foro/detalle_respuesta.html', {
        'respuesta': respuesta_actual,
        'respuestas': respuestas_hijas,
    })

@login_required
def boton_like(request, hilo_id):
    hilo = get_object_or_404(Hilo, pk=hilo_id)

    if hilo.likes.filter(id=request.user.id).exists():
        hilo.likes.remove(request.user)
    else:
        hilo.likes.add(request.user)
        
    return render(request, 'foro/partials/boton_like.html', {'hilo': hilo})

@login_required
def Like_respuesta(request, respuesta_id):
    respuesta = get_object_or_404(Respuesta, id=respuesta_id)
    
    if respuesta.likes.filter(id=request.user.id).exists():
        respuesta.likes.remove(request.user)
    else:
        respuesta.likes.add(request.user)
        
    return render(request, 'foro/partials/boton_like_respuesta.html', {'respuesta': respuesta})

@login_required
def explorar_usuarios(request):
    query = request.GET.get('q_usuarios', '')
    usuarios = []
    
    if query:
        usuarios = UsuarioForo.objects.filter(
            username__icontains=query, is_active=True
        ).exclude(id=request.user.id)[:50]
        
    if request.headers.get('HX-Request') and not request.headers.get('HX-Boosted'):
        return render(request, 'foro/partials/resultados_usuarios.html', {
            'usuarios': usuarios,
            'query': query
        })
        
    return render(request, 'foro/explorar.html', {
        'usuarios': usuarios,
        'query': query
    })

