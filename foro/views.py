import logging
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, TemplateView, UpdateView

from foro.limites import (
    error_peticion,
    limite_busqueda,
    limite_comentarios,
    limite_excedido,
    limite_hilos,
    limite_likes,
    limite_sugerencias,
)
from foro.models import (
    AvisoGlobal,
    Hilo,
    Notificacion,
    Respuesta,
    RespuestaSugerencia,
    Sugerencia,
    Universidad,
)
from foro.utils import (
    MAX_COMENTARIO,
    MAX_HILO,
    MAX_SUGERENCIA,
    MAX_TITULO,
    a_int,
    es_htmx,
    limpiar_texto,
    procesar_imagenes,
    referer_seguro,
)
from usuarios.models import UsuarioForo

logger = logging.getLogger(__name__)

CAMPOS_IMAGEN_HILO = ('imagen', 'imagen2', 'imagen3', 'imagen4')

@method_decorator(limite_hilos, name='post')
class InicioView(LoginRequiredMixin, TemplateView):
    template_name = 'foro/inicio.html'

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)

        busqueda = request.GET.get('q', '')
        universidad_id = a_int(request.GET.get('uni'))

        universidades = cache.get('universidades_list')
        if not universidades:
            universidades = Universidad.objects.all()
            cache.set('universidades_list', universidades, 86400)

        if busqueda:
            universidades = universidades.filter(nombre__icontains=busqueda)

        hilos = Hilo.objects.select_related('universidad', 'autor').filter(activo=True)

        if universidad_id:
            hilos = hilos.filter(universidad_id=universidad_id)

        hilos = hilos.order_by('-fecha_creacion')

        page_number = max(1, a_int(request.GET.get('page'), 1))  # antes: page=0 o negativo daba 500

        items_por_pagina = 15
        offset = (page_number - 1) * items_por_pagina
        limit = offset + items_por_pagina + 1

        hilos_pagina = list(hilos[offset:limit])

        hay_siguiente = len(hilos_pagina) > items_por_pagina
        if hay_siguiente:
            hilos_pagina.pop()

        if request.headers.get('HX-Request') and request.GET.get('page'):
            return render(request, 'foro/partials/hilos_lista.html', {
                'page_obj': hilos_pagina,
                'has_next': hay_siguiente,
                'next_page_number': page_number + 1,
                'busqueda_actual': busqueda,
                'uni_actual': universidad_id or '',
            })

        context['universidades'] = universidades
        context['page_obj'] = hilos_pagina
        context['has_next'] = hay_siguiente
        context['next_page_number'] = page_number + 1
        context['busqueda_actual'] = busqueda
        context['uni_actual'] = universidad_id or ''

        return self.render_to_response(context)

    def post(self, request, *args, **kwargs):
        referer = referer_seguro(request)

        if getattr(request, 'limited', False):
            return limite_excedido(request, "Estás publicando hilos muy rápido. Por favor, espera un momento.", referer)

        titulo, error = limpiar_texto(request.POST.get('titulo'), MAX_TITULO, requerido=False, nombre='El título')
        if error:
            return error_peticion(request, error, referer)

        contenido, error = limpiar_texto(request.POST.get('contenido'), MAX_HILO)
        if error:
            return error_peticion(request, error, referer)

        archivos_subidos = request.FILES.getlist('imagen')
        if len(archivos_subidos) > 4:
            return error_peticion(request, "Solo puedes subir un máximo de 4 imágenes.", referer)

        imagenes, error = procesar_imagenes(archivos_subidos, max_mb=5)
        if error:
            return error_peticion(request, error, referer)

        idem_token = (request.POST.get('idem_token') or '')[:64]
        idem_key = f'idem_{request.user.id}_{idem_token}' if idem_token else None
        if idem_key and not cache.add(idem_key, True, 60):
            return error_peticion(request, "Petición duplicada", referer)

        try:
            nuevo_hilo = Hilo(
                titulo=titulo or "Sin título",
                contenido=contenido,
                autor=request.user,
                universidad=getattr(request.user, 'universidad', None),
            )
            for campo, archivo in zip(CAMPOS_IMAGEN_HILO, imagenes):
                setattr(nuevo_hilo, campo, archivo)
            nuevo_hilo.save()
        except Exception:
            logger.exception("Error creando hilo (usuario %s)", request.user.id)
            if idem_key:
                cache.delete(idem_key)  # deja reintentar con el mismo token
            return error_peticion(
                request, "Ocurrió un error al intentar publicar. Intenta de nuevo.", referer, status=500
            )

        if es_htmx(request):
            return render(request, 'foro/partials/tarjeta_hilo.html', {'hilo': nuevo_hilo})
        return redirect(referer)

@method_decorator(limite_comentarios, name='post')
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
        destino = reverse('detalle_hilo', kwargs={'public_id': self.object.public_id})

        # Reemplaza el chequeo manual de 4s por DB (tenía race condition y costaba una query).
        if getattr(request, 'limited', False):
            return limite_excedido(request, "Estás comentando muy rápido. Espera un momento.", destino)

        contenido, error = limpiar_texto(request.POST.get('contenido'), MAX_COMENTARIO, nombre='El comentario')
        if error:
            return error_peticion(request, error, destino)

        self.object.respuestas.create(contenido=contenido, autor=request.user)
        return redirect(destino)


@login_required
@limite_comentarios
def detalle_respuesta(request, public_id):
    destino = reverse('detalle_respuesta', kwargs={'public_id': public_id})

    if getattr(request, 'limited', False):
        return limite_excedido(request, "Estás comentando muy rápido. Espera un momento.", destino)

    respuesta_actual = get_object_or_404(Respuesta, public_id=public_id, activo=True)
    hilo_original = respuesta_actual.hilo

    if request.method == 'POST':
        contenido, error = limpiar_texto(request.POST.get('contenido'), MAX_COMENTARIO, nombre='El comentario')
        if error:
            return error_peticion(request, error, destino)

        Respuesta.objects.create(
            autor=request.user,
            hilo=hilo_original,
            respuesta_padre=respuesta_actual,
            contenido=contenido,
        )
        return redirect(destino)

    respuestas_hijas = respuesta_actual.respuestas_hijas.filter(activo=True).select_related('autor').annotate(
        conteo_likes=Count('likes', distinct=True)
    ).order_by('fecha_creacion')

    return render(request, 'foro/detalle_respuesta.html', {
        'respuesta': respuesta_actual,
        'respuestas': respuestas_hijas,
    })


@login_required
@require_POST
@limite_likes
def boton_like(request, hilo_id):
    if getattr(request, 'limited', False):
        return limite_excedido(request, "Vas muy rápido con los likes. Espera un momento.", referer_seguro(request))

    with transaction.atomic():
        hilo = get_object_or_404(Hilo.objects.select_for_update(), pk=hilo_id, activo=True)

        if hilo.likes.filter(id=request.user.id).exists():
            hilo.likes.remove(request.user)
            hilo.likes_count = F('likes_count') - 1
        else:
            hilo.likes.add(request.user)
            hilo.likes_count = F('likes_count') + 1

        hilo.save(update_fields=['likes_count'])
        hilo.refresh_from_db()

    return render(request, 'foro/partials/boton_like.html', {'hilo': hilo})

@login_required
@require_POST
@limite_likes
def Like_respuesta(request, respuesta_id):
    if getattr(request, 'limited', False):
        return limite_excedido(request, "Vas muy rápido con los likes. Espera un momento.", referer_seguro(request))

    with transaction.atomic():
        respuesta = get_object_or_404(Respuesta.objects.select_for_update(), id=respuesta_id, activo=True)

        if respuesta.likes.filter(id=request.user.id).exists():
            respuesta.likes.remove(request.user)
        else:
            respuesta.likes.add(request.user)
    return render(request, 'foro/partials/boton_like_respuesta.html', {'respuesta': respuesta})

@login_required
@limite_busqueda
def explorar_usuarios(request):
    if getattr(request, 'limited', False):
        return limite_excedido(request, "Estás buscando muy rápido. Espera un momento.", referer_seguro(request))

    query = request.GET.get('q_usuarios', '').strip()[:50]
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

@method_decorator(limite_sugerencias, name='post')
class SugerenciasCreateView(LoginRequiredMixin, CreateView):
    model = Sugerencia
    fields = ['contenido']
    template_name = 'foro/sugerencias.html'
    success_url = reverse_lazy('sugerencias')

    def post(self, request, *args, **kwargs):
        if getattr(request, 'limited', False):
            return limite_excedido(request, 'Estás enviando sugerencias muy rápido.', reverse('sugerencias'))
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        if len(form.cleaned_data['contenido']) > MAX_SUGERENCIA:
            form.add_error('contenido', f'La sugerencia no puede superar los {MAX_SUGERENCIA} caracteres.')
            return self.form_invalid(form)
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
@limite_comentarios
def detalle_sugerencia(request, public_id):
    destino = reverse('detalle_sugerencia', kwargs={'public_id': public_id})

    if getattr(request, 'limited', False):
        return limite_excedido(request, 'Estás comentando muy rápido.', destino)

    sugerencia = get_object_or_404(Sugerencia, public_id=public_id)

    if request.method == 'POST':
        contenido, error = limpiar_texto(request.POST.get('contenido'), MAX_COMENTARIO, nombre='El comentario')
        if error:
            return error_peticion(request, error, destino)

        respuesta_padre = None
        padre_raw = request.POST.get('respuesta_padre_id')
        if padre_raw:
            padre_id = a_int(padre_raw)
            if padre_id is None:
                raise Http404
            respuesta_padre = get_object_or_404(RespuestaSugerencia, pk=padre_id, sugerencia=sugerencia)

        RespuestaSugerencia.objects.create(
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

        return redirect(destino)

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
@require_POST
@limite_likes
def interaccion_sugerencia(request, public_id, accion):
    destino = referer_seguro(request, reverse('sugerencias'))

    if getattr(request, 'limited', False):
        return limite_excedido(request, "Vas muy rápido. Espera un momento.", destino)

    if accion not in ('like', 'dislike'):
        raise Http404

    with transaction.atomic():
        sugerencia = get_object_or_404(Sugerencia.objects.select_for_update(), public_id=public_id)

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

        else:  # dislike
            if sugerencia.dislikes.filter(id=request.user.id).exists():
                sugerencia.dislikes.remove(request.user)
            else:
                sugerencia.dislikes.add(request.user)
                sugerencia.likes.remove(request.user)

    return redirect(destino)

@login_required
@require_POST
@limite_likes
def like_respuesta_sugerencia(request, respuesta_id):
    if getattr(request, 'limited', False):
        return limite_excedido(request, "Vas muy rápido con los likes. Espera un momento.", referer_seguro(request))

    respuesta = get_object_or_404(RespuestaSugerencia, id=respuesta_id)
    if respuesta.likes.filter(id=request.user.id).exists():
        respuesta.likes.remove(request.user)
    else:
        respuesta.likes.add(request.user)
    return redirect('detalle_sugerencia', public_id=respuesta.sugerencia.public_id)

@login_required
@limite_comentarios
def detalle_respuesta_sugerencia(request, pk):
    destino = reverse('detalle_respuesta_sugerencia', kwargs={'pk': pk})

    if getattr(request, 'limited', False):
        return limite_excedido(request, 'Estás comentando muy rápido.', destino)

    respuesta_actual = get_object_or_404(RespuestaSugerencia, pk=pk)
    sugerencia = respuesta_actual.sugerencia

    if request.method == 'POST':
        contenido, error = limpiar_texto(request.POST.get('contenido'), MAX_COMENTARIO, nombre='El comentario')
        if error:
            return error_peticion(request, error, destino)

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

        return redirect(destino)

    respuestas_hijas = respuesta_actual.respuestas_hijas.all().select_related('autor').annotate(
        conteo_likes=Count('likes', distinct=True)
    ).order_by('fecha_creacion')

    return render(request, 'foro/detalle_respuesta_sugerencia.html', {
        'respuesta_padre': respuesta_actual,
        'sugerencia': sugerencia,
        'respuestas': respuestas_hijas,
    })


class EditarHilos(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = Hilo
    fields = ['contenido', 'imagen', 'imagen2', 'imagen3', 'imagen4']
    template_name = 'foro/editar_hilo.html'
    success_url = reverse_lazy('inicio')
    slug_field = 'public_id'
    slug_url_kwarg = 'public_id'

    def test_func(self):
        return self.get_object().autor == self.request.user

    def form_valid(self, form):
        _, error = limpiar_texto(form.cleaned_data.get('contenido'), MAX_HILO)
        if error:
            form.add_error('contenido', error)
            return self.form_invalid(form)

        for campo in CAMPOS_IMAGEN_HILO:
            archivo = self.request.FILES.get(campo)
            if archivo:
                limpios, error = procesar_imagenes([archivo], max_mb=5)
                if error:
                    form.add_error(campo, error)
                    return self.form_invalid(form)
                setattr(form.instance, campo, limpios[0])
        return super().form_valid(form)


class EliminarHilos(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = Hilo
    template_name = 'foro/eliminar_hilo.html'
    success_url = reverse_lazy('inicio')
    slug_field = 'public_id'
    slug_url_kwarg = 'public_id'

    def test_func(self):
        return self.get_object().autor == self.request.user


@login_required
def obtener_tarjeta_hilo(request, hilo_id):
    hilo = get_object_or_404(Hilo, id=hilo_id, activo=True)
    return render(request, 'foro/partials/tarjeta_hilo.html', {'hilo': hilo})


@login_required
def obtener_tarjeta_respuesta(request, respuesta_id):
    respuesta = get_object_or_404(Respuesta, id=respuesta_id, activo=True)
    return render(request, 'foro/partials/tarjeta_respuesta.html', {'hijo': respuesta})


@login_required
def obtener_tarjeta_notificacion(request, notificacion_id):
    notif = get_object_or_404(
        Notificacion.objects.select_related('hilo', 'respuesta', 'sugerencia', 'respuesta_sugerencia')
                              .prefetch_related('actores'),
        id=notificacion_id,
        destinatario=request.user
    )
    return render(request, 'foro/partials/item_notificacion.html', {'notif': notif})


@login_required
def obtener_tarjeta_sugerencia(request, sugerencia_id):
    sugerencia = get_object_or_404(Sugerencia, id=sugerencia_id)
    return render(request, 'foro/partials/tarjeta_sugerencia.html', {'sugerencia': sugerencia})


@login_required
def obtener_tarjeta_respuesta_sugerencia(request, respuesta_id):
    resp = get_object_or_404(RespuestaSugerencia, id=respuesta_id)
    return render(request, 'foro/partials/item_respuesta_sug.html', {'resp': resp})


@login_required
@require_POST
def marcar_aviso_visto(request, aviso_id):
    try:
        aviso = AvisoGlobal.objects.get(id=aviso_id, activo=True)
        aviso.visto_por.add(request.user)
        return JsonResponse({'status': 'ok', 'mensaje': 'Aviso marcado como visto'})
    except AvisoGlobal.DoesNotExist:
        return JsonResponse({'status': 'error', 'mensaje': 'Aviso no encontrado'}, status=404)