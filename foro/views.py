import json
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import CreateView, DeleteView, DetailView, TemplateView, UpdateView

from foro.limites import (
    consumir_cuota,
    cuota_agotada,
    error_peticion,
    limite_busqueda,
    limite_excedido,
    limite_likes,
    limite_reportes,
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
from foro.notificaciones import contadores_usuario, notificar, retirar_notificacion
from foro.utils import (
    MAX_COMENTARIO,
    MAX_HILO,
    MAX_SUGERENCIA,
    MAX_TITULO,
    a_int,
    asignar_imagenes_en_paralelo,
    es_htmx,
    limpiar_texto,
    procesar_imagenes,
    referer_seguro,
)
from usuarios.models import UsuarioForo

logger = logging.getLogger(__name__)

CAMPOS_IMAGEN_HILO = ('imagen', 'imagen2', 'imagen3', 'imagen4')
MSG_COMENTANDO_RAPIDO = "Estás comentando muy rápido. Espera un momento."


class InicioView(LoginRequiredMixin, TemplateView):
    template_name = 'foro/inicio.html'
    items_por_pagina = 15

    def get(self, request, *args, **kwargs):
        busqueda = request.GET.get('q', '').strip()[:50]
        universidad_id = a_int(request.GET.get('uni'))
        # Paginación por cursor ("los anteriores a este id"): cuesta lo mismo en la página 1 que en
        # la 100, a diferencia de OFFSET, que obliga a la BD a recorrer todo lo anterior.
        antes = a_int(request.GET.get('antes'))

        hilos = Hilo.objects.visibles_para(request.user).con_conteos(request.user)
        if universidad_id:
            hilos = hilos.filter(universidad_id=universidad_id)
        if antes:
            hilos = hilos.filter(id__lt=antes)
        hilos = hilos.order_by('-id')  # los ids crecen con la fecha de creación

        hilos_pagina = list(hilos[:self.items_por_pagina + 1])
        hay_siguiente = len(hilos_pagina) > self.items_por_pagina
        if hay_siguiente:
            hilos_pagina.pop()

        contexto_lista = {
            'page_obj': hilos_pagina,
            'has_next': hay_siguiente,
            'cursor_siguiente': hilos_pagina[-1].id if hilos_pagina else '',
            'busqueda_actual': busqueda,
            'uni_actual': universidad_id or '',
        }
        if request.headers.get('HX-Request') and antes:
            return render(request, 'foro/partials/hilos_lista.html', contexto_lista)

        universidades = Universidad.cacheadas()
        if busqueda:
            universidades = [u for u in universidades if busqueda.lower() in u.nombre.lower()]

        context = self.get_context_data(**kwargs)
        context.update(contexto_lista, universidades=universidades)
        return self.render_to_response(context)

    def post(self, request, *args, **kwargs):
        referer = referer_seguro(request)

        if cuota_agotada(request, 'hilos'):
            return limite_excedido(request, "Estás publicando hilos muy rápido. Por favor, espera un momento.", referer)

        titulo, error = limpiar_texto(request.POST.get('titulo'), MAX_TITULO, requerido=False, nombre='El título')
        if error:
            return error_peticion(request, error, referer)

        contenido, error = limpiar_texto(request.POST.get('contenido'), MAX_HILO)
        if error:
            return error_peticion(request, error, referer)

        archivos_subidos = request.FILES.getlist('imagen')
        if len(archivos_subidos) > len(CAMPOS_IMAGEN_HILO):
            return error_peticion(request, "Solo puedes subir un máximo de 4 imágenes.", referer)

        imagenes, error = procesar_imagenes(archivos_subidos, max_mb=5)
        if error:
            return error_peticion(request, error, referer)

        idem_token = (request.POST.get('idem_token') or '')[:64]
        idem_key = f'idem_{request.user.id}_{idem_token}' if idem_token else None
        # add() es atómico: True = primera vez, False = ya existía (duplicado).
        # Con Redis caído (IGNORE_EXCEPTIONS) devuelve None: se deja publicar en vez de bloquear.
        if idem_key and cache.add(idem_key, True, 60) is False:
            return error_peticion(request, "Petición duplicada", referer, status=409)

        deshacer_subida = None
        try:
            nuevo_hilo = Hilo(
                titulo=titulo or "Sin título",
                contenido=contenido,
                autor=request.user,
                universidad=request.user.universidad,
            )
            if imagenes:
                deshacer_subida = asignar_imagenes_en_paralelo(nuevo_hilo, CAMPOS_IMAGEN_HILO, imagenes)
            nuevo_hilo.save()
        except Exception:
            logger.exception("Error creando hilo (usuario %s)", request.user.id)
            if deshacer_subida:
                deshacer_subida()  # no dejar imágenes huérfanas en R2
            if idem_key:
                cache.delete(idem_key)  # deja reintentar con el mismo token
            return error_peticion(
                request, "Ocurrió un error al intentar publicar. Intenta de nuevo.", referer, status=500
            )

        consumir_cuota(request, 'hilos')

        if es_htmx(request):
            nuevo_hilo.conteo_respuestas = 0
            nuevo_hilo.les_gusta_al_usuario = False
            return render(request, 'foro/partials/tarjeta_hilo.html', {'hilo': nuevo_hilo})
        return redirect(referer)


class detalleHilo(LoginRequiredMixin, DetailView):
    model = Hilo
    template_name = 'foro/detalle_hilo.html'
    context_object_name = 'hilo'
    slug_field = 'public_id'
    slug_url_kwarg = 'public_id'

    def get_queryset(self):
        return Hilo.objects.filter(activo=True).con_conteos(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        respuestas = self.object.respuestas.filter(
            activo=True, respuesta_padre__isnull=True
        ).select_related('autor').annotate(
            conteo_likes=Count('likes', distinct=True),
            conteo_respuestas_hijas=Count('respuestas_hijas', filter=Q(respuestas_hijas__activo=True), distinct=True),
            les_gusta_al_usuario=Exists(
                Respuesta.likes.through.objects.filter(respuesta_id=OuterRef('pk'), usuarioforo_id=self.request.user.pk)
            ),
        )
        context['respuestas'] = respuestas.order_by('fecha_creacion')
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        destino = reverse('detalle_hilo', kwargs={'public_id': self.object.public_id})

        if cuota_agotada(request, 'comentarios'):
            return limite_excedido(request, MSG_COMENTANDO_RAPIDO, destino)

        contenido, error = limpiar_texto(request.POST.get('contenido'), MAX_COMENTARIO, nombre='El comentario')
        if error:
            return error_peticion(request, error, destino)

        self.object.respuestas.create(contenido=contenido, autor=request.user)
        consumir_cuota(request, 'comentarios')
        return redirect(destino)


@login_required
def detalle_respuesta(request, public_id):
    destino = reverse('detalle_respuesta', kwargs={'public_id': public_id})
    respuesta_actual = get_object_or_404(
        Respuesta.objects.select_related('autor', 'hilo'), public_id=public_id, activo=True, hilo__activo=True
    )

    if request.method == 'POST':
        if cuota_agotada(request, 'comentarios'):
            return limite_excedido(request, MSG_COMENTANDO_RAPIDO, destino)

        contenido, error = limpiar_texto(request.POST.get('contenido'), MAX_COMENTARIO, nombre='El comentario')
        if error:
            return error_peticion(request, error, destino)

        Respuesta.objects.create(
            autor=request.user,
            hilo=respuesta_actual.hilo,
            respuesta_padre=respuesta_actual,
            contenido=contenido,
        )
        consumir_cuota(request, 'comentarios')
        return redirect(destino)

    respuestas_hijas = respuesta_actual.respuestas_hijas.filter(activo=True).select_related('autor').annotate(
        conteo_likes=Count('likes', distinct=True),
        conteo_respuestas_hijas=Count('respuestas_hijas', filter=Q(respuestas_hijas__activo=True), distinct=True),
        les_gusta_al_usuario=Exists(
            Respuesta.likes.through.objects.filter(respuesta_id=OuterRef('pk'), usuarioforo_id=request.user.pk)
        ),
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
            hilo.les_gusta_al_usuario = False
        else:
            hilo.likes.add(request.user)
            hilo.likes_count = F('likes_count') + 1
            hilo.les_gusta_al_usuario = True

        hilo.save(update_fields=['likes_count'])
        hilo.refresh_from_db(fields=['likes_count'])

    return render(request, 'foro/partials/boton_like.html', {'hilo': hilo})


@login_required
@require_POST
@limite_likes
def Like_respuesta(request, respuesta_id):
    if getattr(request, 'limited', False):
        return limite_excedido(request, "Vas muy rápido con los likes. Espera un momento.", referer_seguro(request))

    with transaction.atomic():
        respuesta = get_object_or_404(
            Respuesta.objects.select_for_update(), id=respuesta_id, activo=True, hilo__activo=True
        )
        if respuesta.likes.filter(id=request.user.id).exists():
            respuesta.likes.remove(request.user)
            respuesta.les_gusta_al_usuario = False
        else:
            respuesta.likes.add(request.user)
            respuesta.les_gusta_al_usuario = True
        respuesta.conteo_likes = respuesta.likes.count()
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

    contexto = {'usuarios': usuarios, 'query': query}
    if request.headers.get('HX-Request') and not request.headers.get('HX-Boosted'):
        return render(request, 'foro/partials/resultados_usuarios.html', contexto)
    return render(request, 'foro/explorar.html', contexto)


@login_required
def notificaciones(request):
    todas = list(
        Notificacion.objects.filter(destinatario=request.user)
        .select_related('hilo', 'respuesta', 'sugerencia', 'respuesta_sugerencia')
        .prefetch_related('actores')[:200]
    )

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
        # update() no dispara auto_now, así que no reordena las notificaciones.
        Notificacion.objects.filter(id__in=ids_no_leidas).update(leido=True)

    contexto = {'grupos': grupos, 'ids_no_leidas': ids_no_leidas}

    if request.headers.get('HX-Request') == 'true':
        return render(request, 'foro/partials/notificaciones_lista.html', contexto)
    return render(request, 'foro/notificaciones.html', contexto)


@login_required
@require_GET
def estado_tiempo_real(request):
    """
    Contadores privados para refrescar badges y el chat sin exponer datos a Supabase.
    La web lo consulta periódicamente (ver base.html) en lugar de escuchar tablas privadas.
    """
    return JsonResponse(contadores_usuario(request.user))


class SugerenciasCreateView(LoginRequiredMixin, CreateView):
    model = Sugerencia
    fields = ['contenido']
    template_name = 'foro/sugerencias.html'
    success_url = reverse_lazy('sugerencias')

    def post(self, request, *args, **kwargs):
        if cuota_agotada(request, 'sugerencias'):
            return limite_excedido(request, 'Estás enviando sugerencias muy rápido.', reverse('sugerencias'))
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        contenido, error = limpiar_texto(form.cleaned_data['contenido'], MAX_SUGERENCIA, nombre='La sugerencia')
        if error:
            form.add_error('contenido', error)
            return self.form_invalid(form)
        form.instance.contenido = contenido
        form.instance.usuario = self.request.user
        respuesta = super().form_valid(form)
        consumir_cuota(self.request, 'sugerencias')
        return respuesta

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sugerencias'] = Sugerencia.objects.con_conteos(self.request.user)[:50]
        return context


@login_required
def detalle_sugerencia(request, public_id):
    destino = reverse('detalle_sugerencia', kwargs={'public_id': public_id})
    sugerencia = get_object_or_404(Sugerencia.objects.con_conteos(request.user), public_id=public_id)

    if request.method == 'POST':
        if cuota_agotada(request, 'comentarios'):
            return limite_excedido(request, MSG_COMENTANDO_RAPIDO, destino)

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

        nueva = RespuestaSugerencia.objects.create(
            sugerencia=sugerencia,
            respuesta_padre=respuesta_padre,
            autor=request.user,
            contenido=contenido
        )
        consumir_cuota(request, 'comentarios')

        destinatario = respuesta_padre.autor if respuesta_padre else sugerencia.usuario
        notificar(
            destinatario, Notificacion.TIPO_COMENTARIO_SUGERENCIA, request.user,
            actualizar={'respuesta_sugerencia': nueva}, sugerencia=sugerencia,
        )
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
        ya_like = sugerencia.likes.filter(id=request.user.id).exists()

        if accion == 'like':
            if ya_like:
                sugerencia.likes.remove(request.user)
            else:
                sugerencia.likes.add(request.user)
                sugerencia.dislikes.remove(request.user)
        else:
            if sugerencia.dislikes.filter(id=request.user.id).exists():
                sugerencia.dislikes.remove(request.user)
            else:
                sugerencia.dislikes.add(request.user)
                sugerencia.likes.remove(request.user)

        tiene_like = accion == 'like' and not ya_like
        if tiene_like:
            notificar(sugerencia.usuario, Notificacion.TIPO_LIKE_SUGERENCIA, request.user, sugerencia=sugerencia)
        elif ya_like:
            retirar_notificacion(
                sugerencia.usuario, Notificacion.TIPO_LIKE_SUGERENCIA, [request.user.pk], sugerencia=sugerencia
            )

    return redirect(destino)


@login_required
@require_POST
@limite_likes
def like_respuesta_sugerencia(request, respuesta_id):
    if getattr(request, 'limited', False):
        return limite_excedido(request, "Vas muy rápido con los likes. Espera un momento.", referer_seguro(request))

    respuesta = get_object_or_404(RespuestaSugerencia.objects.select_related('sugerencia'), id=respuesta_id)
    if respuesta.likes.filter(id=request.user.id).exists():
        respuesta.likes.remove(request.user)
    else:
        respuesta.likes.add(request.user)
    return redirect(referer_seguro(request, reverse('detalle_sugerencia', kwargs={'public_id': respuesta.sugerencia.public_id})))


@login_required
def detalle_respuesta_sugerencia(request, pk):
    destino = reverse('detalle_respuesta_sugerencia', kwargs={'pk': pk})
    respuesta_actual = get_object_or_404(RespuestaSugerencia.objects.select_related('sugerencia', 'autor'), pk=pk)
    sugerencia = respuesta_actual.sugerencia

    if request.method == 'POST':
        if cuota_agotada(request, 'comentarios'):
            return limite_excedido(request, 'Estás comentando muy rápido.', destino)

        contenido, error = limpiar_texto(request.POST.get('contenido'), MAX_COMENTARIO, nombre='El comentario')
        if error:
            return error_peticion(request, error, destino)

        nueva_respuesta = RespuestaSugerencia.objects.create(
            sugerencia=sugerencia,
            respuesta_padre=respuesta_actual,
            autor=request.user,
            contenido=contenido
        )
        consumir_cuota(request, 'comentarios')
        notificar(
            respuesta_actual.autor, Notificacion.TIPO_COMENTARIO_SUGERENCIA, request.user,
            actualizar={'respuesta_sugerencia': nueva_respuesta}, sugerencia=sugerencia,
        )
        return redirect(destino)

    respuestas_hijas = respuesta_actual.respuestas_hijas.all().select_related('autor').prefetch_related('likes').order_by('fecha_creacion')

    return render(request, 'foro/detalle_respuesta_sugerencia.html', {
        'respuesta_padre': respuesta_actual,
        'sugerencia': sugerencia,
        'respuestas': respuestas_hijas,
    })


class HiloPropioMixin(LoginRequiredMixin):
    """Solo el autor puede editar/eliminar; a los demás les responde 404 (no revela que existe)."""
    model = Hilo
    slug_field = 'public_id'
    slug_url_kwarg = 'public_id'
    success_url = reverse_lazy('inicio')

    def get_queryset(self):
        return Hilo.objects.filter(autor=self.request.user)


class EditarHilos(HiloPropioMixin, UpdateView):
    fields = ['contenido', 'imagen', 'imagen2', 'imagen3', 'imagen4']
    template_name = 'foro/editar_hilo.html'

    def form_valid(self, form):
        contenido, error = limpiar_texto(form.cleaned_data.get('contenido'), MAX_HILO)
        if error:
            form.add_error('contenido', error)
            return self.form_invalid(form)
        form.instance.contenido = contenido

        for campo in CAMPOS_IMAGEN_HILO:
            archivo = self.request.FILES.get(campo)
            if archivo:
                limpios, error = procesar_imagenes([archivo], max_mb=5)
                if error:
                    form.add_error(campo, error)
                    return self.form_invalid(form)
                setattr(form.instance, campo, limpios[0])
        return super().form_valid(form)


class EliminarHilos(HiloPropioMixin, DeleteView):
    template_name = 'foro/eliminar_hilo.html'


@login_required
def obtener_tarjeta_hilo(request, hilo_id):
    hilo = get_object_or_404(Hilo.objects.visibles_para(request.user).con_conteos(request.user), id=hilo_id)
    return render(request, 'foro/partials/tarjeta_hilo.html', {'hilo': hilo})


@login_required
def obtener_tarjeta_respuesta(request, respuesta_id):
    respuesta = get_object_or_404(
        Respuesta.objects.select_related('autor').annotate(
            conteo_likes=Count('likes', distinct=True),
            conteo_respuestas_hijas=Count('respuestas_hijas', filter=Q(respuestas_hijas__activo=True), distinct=True),
        ),
        id=respuesta_id, activo=True, hilo__activo=True,
    )
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
    sugerencia = get_object_or_404(Sugerencia.objects.con_conteos(request.user), id=sugerencia_id)
    return render(request, 'foro/partials/tarjeta_sugerencia.html', {'sugerencia': sugerencia})


@login_required
def obtener_tarjeta_respuesta_sugerencia(request, respuesta_id):
    resp = get_object_or_404(RespuestaSugerencia.objects.select_related('autor'), id=respuesta_id)
    return render(request, 'foro/partials/item_respuesta_sug.html', {'resp': resp})


@login_required
@require_POST
def marcar_aviso_visto(request, aviso_id):
    try:
        aviso = AvisoGlobal.objects.get(id=aviso_id, activo=True)
    except AvisoGlobal.DoesNotExist:
        return JsonResponse({'status': 'error', 'mensaje': 'Aviso no encontrado'}, status=404)
    aviso.visto_por.add(request.user)
    return JsonResponse({'status': 'ok', 'mensaje': 'Aviso marcado como visto'})


@login_required
@require_POST
@limite_reportes
def reportar_hilo(request, public_id):
    if getattr(request, 'limited', False):
        return limite_excedido(request, "Has enviado muchos reportes. Intenta más tarde.", referer_seguro(request))

    hilo = get_object_or_404(Hilo, public_id=public_id, activo=True)
    if hilo.autor_id == request.user.id:
        return error_peticion(request, "No puedes reportar tu propio hilo.", referer_seguro(request))

    hilo.reportes.add(request.user)  # add() ignora duplicados

    # Solo cuentan cuentas con cierta antigüedad, para que no baste con crear cuentas nuevas y
    # tumbar hilos ajenos. Los hilos ocultados se pueden revisar/reactivar desde el admin.
    fecha_limite = timezone.now() - settings.REPORTES_ANTIGUEDAD_MINIMA
    reportes_validos = hilo.reportes.filter(date_joined__lte=fecha_limite, is_active=True).count()
    if reportes_validos >= settings.REPORTES_PARA_OCULTAR:
        Hilo.objects.filter(pk=hilo.pk).update(activo=False)
        logger.warning("Hilo %s ocultado automáticamente tras %s reportes", hilo.pk, reportes_validos)

    resp = HttpResponse(status=200)
    resp['HX-Trigger'] = json.dumps({'mostrarAviso': 'Gracias por tu reporte. Ya no verás este hilo.'})
    resp['HX-Reswap'] = 'delete'
    return resp
