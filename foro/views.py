from django.core.cache import cache
from django.db.models import Q, Count
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, TemplateView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from foro.models import Hilo, Notificacion, Respuesta, Sugerencia, Universidad, RespuestaSugerencia
from django.shortcuts import redirect, render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timedelta
from django.core.paginator import Paginator
from django.template.response import TemplateResponse
from django.contrib import messages
from usuarios.models import UsuarioForo
from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme

@method_decorator(ratelimit(key='user', rate='5/m', block=False), name='post')
class InicioView(LoginRequiredMixin, TemplateView):
    template_name = 'foro/inicio.html'

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        
        busqueda = request.GET.get('q', '')
        universidad_id = request.GET.get('uni', '')

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
        ).order_by('-fecha_creacion')

        paginator = Paginator(hilos, 15)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)

        if request.headers.get('HX-Request') and request.GET.get('page'):
            return render(request, 'foro/partials/hilos_lista.html', {
                'page_obj': page_obj,
                'busqueda_actual': busqueda,
                'uni_actual': universidad_id
            })

        context['universidades'] = universidades
        context['page_obj'] = page_obj
        context['busqueda_actual'] = busqueda
        context['uni_actual'] = int(universidad_id) if universidad_id.isdigit() else ''

        return self.render_to_response(context)

    def post(self, request, *args, **kwargs):

        referer = request.META.get('HTTP_REFERER', '/')
        if not url_has_allowed_host_and_scheme(url=referer, allowed_hosts={request.get_host()}):
            referer = '/'

        if getattr(request, 'limited', False):
            messages.error(request, "Estás publicando hilos muy rápido. Por favor, espera un minuto.")
            return redirect(referer)

        idem_token = request.POST.get('idem_token')
        if idem_token:
            if cache.get(f'idem_{idem_token}'):
                return redirect(referer)
            cache.set(f'idem_{idem_token}', True, 60)

        contenido = request.POST.get('contenido')
        titulo = request.POST.get('titulo')
        
        archivos = request.FILES.getlist('imagen')[:4]

        limite_tamano = 5 * 1024 * 1024
        for archivo in archivos:
            if archivo.size > limite_tamano:
                return redirect(referer)

        if contenido:
            nuevo_hilo = Hilo.objects.create(
                titulo=titulo,
                contenido=contenido,
                autor=request.user,
                universidad=getattr(request.user, 'universidad', None)
            )

            if len(archivos) > 0: nuevo_hilo.imagen = archivos[0]
            if len(archivos) > 1: nuevo_hilo.imagen2 = archivos[1]
            if len(archivos) > 2: nuevo_hilo.imagen3 = archivos[2]
            if len(archivos) > 3: nuevo_hilo.imagen4 = archivos[3]
            
            if archivos:
                nuevo_hilo.save()

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('HX-Request'):
                return render(request, 'foro/partials/tarjeta_hilo.html', {'hilo': nuevo_hilo})

        return redirect(referer)

class detalleHilo(LoginRequiredMixin, DetailView):
    model = Hilo
    template_name = 'foro/detalle_hilo.html'
    context_object_name = 'hilo'
    slug_field = 'public_id'
    slug_url_kwarg = 'public_id'
    queryset = Hilo.objects.filter(activo=True)

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

        ultimo_comentario = Respuesta.objects.filter(autor=request.user).order_by('-fecha_creacion').first()
        if ultimo_comentario:
            tiempo_transcurrido = timezone.now() - ultimo_comentario.fecha_creacion
            if tiempo_transcurrido < timedelta(seconds=4):
                messages.error(request, "Espera unos segundos antes de publicar otro comentario.")
                return redirect('detalle_hilo', public_id=self.object.public_id)

        if contenido:
            self.object.respuestas.create(
                contenido=contenido,
                autor=request.user
            ) 

        return redirect('detalle_hilo', public_id=self.object.public_id)    

@login_required
@ratelimit(key='user', rate='10/m', method='POST', block=False)
def detalle_respuesta(request, public_id):
    if getattr(request, 'limited', False):
        messages.error(request, "Estás comentando muy rápido. Espera un momento.")
        return redirect('detalle_respuesta', public_id=public_id) 

    respuesta_actual = get_object_or_404(Respuesta, public_id=public_id, activo=True) 
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
            return redirect('detalle_respuesta', public_id=respuesta_actual.public_id) 

    respuestas_hijas = respuesta_actual.respuestas_hijas.filter(activo=True).select_related('autor').annotate(
        conteo_likes=Count('likes', distinct=True)
    ).order_by('fecha_creacion')

    return render(request, 'foro/detalle_respuesta.html', {
        'respuesta': respuesta_actual,
        'respuestas': respuestas_hijas,
    })


@login_required
@ratelimit(key='user', rate='15/m', block=False)
def boton_like(request, hilo_id):
    if getattr(request, 'limited', False):
        return JsonResponse({'error': 'Rate limit excedido'}, status=429)
    
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

@login_required
def notificaciones(request):
    todas = list(Notificacion.objects.filter(destinatario=request.user)
                 .select_related('hilo', 'respuesta').prefetch_related('actores'))

    ahora = timezone.now()
    grupos = {'semana': [], 'mes': [], 'anteriores': []}
    ids_no_leidas = set()

    for notif in todas:
        if not notif.leido:
            ids_no_leidas.add(notif.id)
            
        if notif.ultima_actividad >= ahora - timedelta(days=7):
            grupos['semana'].append(notif)
        elif notif.ultima_actividad >= ahora - timedelta(days=30):
            grupos['mes'].append(notif)
        else:
            grupos['anteriores'].append(notif)

    if ids_no_leidas:
        Notificacion.objects.filter(id__in=ids_no_leidas).update(leido=True)

    contexto = {'grupos': grupos, 'ids_no_leidas': ids_no_leidas}

    if request.headers.get('HX-Request') == 'true':
        return render(request, 'foro/partials/notificaciones_lista.html', contexto)
    return render(request, 'foro/notificaciones_lista.html', contexto)


class SugerenciasCreateView(LoginRequiredMixin, CreateView):
    model = Sugerencia
    fields = ['contenido']
    template_name = 'foro/sugerencias.html'
    success_url = reverse_lazy('sugerencias')

    def form_valid(self, form):
        if self.request.user.is_authenticated:
            form.instance.usuario = self.request.user
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sugerencias'] = Sugerencia.objects.select_related('usuario').annotate(
            conteo_likes=Count('likes', distinct=True),
            conteo_dislikes=Count('dislikes', distinct=True),
            conteo_respuestas=Count('respuestas', distinct=True),
        )[:50]
        return context

@login_required
def detalle_sugerencia(request, public_id):
    sugerencia = get_object_or_404(Sugerencia, public_id=public_id)
    
    if request.method == 'POST':
        contenido = request.POST.get('contenido')
        respuesta_padre_id = request.POST.get('respuesta_padre_id')
        
        if contenido:
            respuesta_padre = None
            if respuesta_padre_id:
                respuesta_padre = get_object_or_404(RespuestaSugerencia, pk=respuesta_padre_id, sugerencia=sugerencia)

            nueva_respuesta = RespuestaSugerencia.objects.create(
                sugerencia=sugerencia,
                respuesta_padre=respuesta_padre,
                autor=request.user,
                contenido=contenido
            )
            
            destinatario = respuesta_padre.autor if respuesta_padre else sugerencia.usuario
            if destinatario and destinatario != request.user:
                notif, created = Notificacion.objects.get_or_create(
                    destinatario=destinatario,
                    tipo=Notificacion.TIPO_COMENTARIO_SUGERENCIA,
                    sugerencia=sugerencia,
                    leido=False
                )
                notif.actores.add(request.user)
                notif.save()
                
            return redirect('detalle_sugerencia', public_id=sugerencia.public_id)

    respuestas_principales = sugerencia.respuestas.filter(respuesta_padre__isnull=True).select_related('autor').prefetch_related(
        'likes',
        'respuestas_hijas__autor',
        'respuestas_hijas__likes',
        'respuestas_hijas__respuestas_hijas'
    )

    return render(request, 'foro/detalle_sugerencia.html', {
        'sugerencia': sugerencia,
        'respuestas': respuestas_principales
    })


@login_required
def interaccion_sugerencia(request, public_id, accion):
    sugerencia = get_object_or_404(Sugerencia, public_id=public_id)

    if accion == 'like':
        if sugerencia.likes.filter(id=request.user.id).exists():
            sugerencia.likes.remove(request.user)
        else:
            sugerencia.likes.add(request.user)
            sugerencia.dislikes.remove(request.user)

            if sugerencia.usuario and sugerencia.usuario != request.user:
                notif, created = Notificacion.objects.get_or_create(
                    destinatario=sugerencia.usuario,
                    tipo=Notificacion.TIPO_LIKE_SUGERENCIA,
                    sugerencia=sugerencia,
                    leido=False
                )
                notif.actores.add(request.user)
                notif.save()

    elif accion == 'dislike':
        if sugerencia.dislikes.filter(id=request.user.id).exists():
            sugerencia.dislikes.remove(request.user)
        else:
            sugerencia.dislikes.add(request.user)
            sugerencia.likes.remove(request.user)

    siguiente = request.META.get('HTTP_REFERER')
    if siguiente and url_has_allowed_host_and_scheme(url=siguiente, allowed_hosts={request.get_host()}):
        return redirect(siguiente)
    return redirect('sugerencias')


@login_required
def like_respuesta_sugerencia(request, respuesta_id):
    respuesta = get_object_or_404(RespuestaSugerencia, id=respuesta_id)
    if respuesta.likes.filter(id=request.user.id).exists():
        respuesta.likes.remove(request.user)
    else:
        respuesta.likes.add(request.user)
    return redirect('detalle_sugerencia', public_id=respuesta.sugerencia.public_id)

@login_required
def detalle_respuesta_sugerencia(request, pk):
    respuesta_actual = get_object_or_404(RespuestaSugerencia, pk=pk)
    sugerencia = respuesta_actual.sugerencia
    
    if request.method == 'POST':
        contenido = request.POST.get('contenido')
        if contenido:
            nueva_respuesta = RespuestaSugerencia.objects.create(
                sugerencia=sugerencia,
                respuesta_padre=respuesta_actual,
                autor=request.user,
                contenido=contenido
            )
            
            destinatario = respuesta_actual.autor
            if destinatario and destinatario != request.user:
                notif, created = Notificacion.objects.get_or_create(
                    destinatario=destinatario,
                    tipo=Notificacion.TIPO_COMENTARIO_SUGERENCIA,
                    sugerencia=sugerencia,
                    leido=False
                )
                notif.actores.add(request.user)
                notif.respuesta_sugerencia = nueva_respuesta
                notif.save()
                
            return redirect('detalle_respuesta_sugerencia', pk=respuesta_actual.pk)

    respuestas_hijas = respuesta_actual.respuestas_hijas.all().select_related('autor').annotate(
        conteo_likes=Count('likes', distinct=True)
    ).order_by('fecha_creacion')

    return render(request, 'foro/detalle_respuesta_sugerencia.html', {
        'respuesta_padre': respuesta_actual,
        'sugerencia': sugerencia,
        'respuestas': respuestas_hijas,
    })

class EditarHilos(LoginRequiredMixin,UserPassesTestMixin,UpdateView):
    model = Hilo
    fields = ['contenido', 'imagen', 'imagen2', 'imagen3', 'imagen4'] 
    template_name = 'foro/editar_hilo.html'
    success_url = reverse_lazy('inicio')
    slug_field = 'public_id'
    slug_url_kwarg = 'public_id'

    def test_func(self):
        return self.get_object().autor == self.request.user

class EliminarHilos(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = Hilo
    template_name = 'foro/eliminar_hilo.html'
    success_url = reverse_lazy('inicio')
    slug_field = 'public_id'
    slug_url_kwarg = 'public_id'

    def test_func(self):
        return self.get_object().autor == self.request.user


