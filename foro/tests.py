import io
import json
import shutil
from unittest import mock
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from foro.models import Hilo, Notificacion, Respuesta, RespuestaSugerencia, Sugerencia
from usuarios.models import Mensaje, Universidad, UsuarioForo


def tearDownModule():
    shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)


def imagen_png(nombre='a.png'):
    buffer = io.BytesIO()
    Image.new('RGB', (20, 20), 'red').save(buffer, 'PNG')
    return SimpleUploadedFile(nombre, buffer.getvalue(), content_type='image/png')


class BaseForoTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.uni = Universidad.objects.create(nombre='UASD')
        cls.ana = UsuarioForo.objects.create_user('ana', password='x', universidad=cls.uni)
        cls.bob = UsuarioForo.objects.create_user('bob', password='x', universidad=cls.uni)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.ana)

    def como(self, usuario):
        self.client.force_login(usuario)


class AccesoTest(BaseForoTest):
    def test_paginas_privadas_redirigen_a_login(self):
        self.client.logout()
        for nombre in ['inicio', 'explorar', 'notificaciones', 'sugerencias', 'estado_tiempo_real']:
            respuesta = self.client.get(reverse(nombre))
            self.assertEqual(respuesta.status_code, 302, nombre)
            self.assertIn('/login/', respuesta['Location'])

    def test_paginacion_con_valores_raros_no_falla(self):
        for q in ['?page=0', '?page=-5', '?page=abc', '?page=99999999999999', '?uni=abc', '?q=UA']:
            self.assertEqual(self.client.get(reverse('inicio') + q).status_code, 200, q)


class CrearHiloTest(BaseForoTest):
    def publicar(self, **datos):
        return self.client.post(reverse('inicio'), datos)

    def test_crea_hilo_con_imagenes_limpias(self):
        self.publicar(titulo='T', contenido='Hola', imagen=[imagen_png(), imagen_png()])
        hilo = Hilo.objects.get()
        self.assertEqual(hilo.universidad, self.uni)
        self.assertRegex(hilo.imagen.name, r'[0-9a-f]{32}\.png$')
        self.assertTrue(hilo.imagen2)

    def test_rechaza_contenido_invalido(self):
        self.publicar(contenido='   ')
        self.publicar(contenido='x' * 501)
        self.publicar(contenido='hola', imagen=[imagen_png() for _ in range(5)])
        self.publicar(contenido='hola', imagen=[SimpleUploadedFile('x.png', b'no soy imagen')])
        self.assertFalse(Hilo.objects.exists())

    def test_errores_de_validacion_no_gastan_cuota(self):
        for _ in range(6):
            self.publicar(contenido='')
        self.publicar(contenido='valido')
        self.assertEqual(Hilo.objects.count(), 1)

    def test_cuota_de_publicacion(self):
        for i in range(6):
            self.publicar(contenido=f'hilo {i}')
        self.assertEqual(Hilo.objects.count(), 5)

    def test_token_idempotente_evita_duplicados(self):
        self.publicar(contenido='uno', idem_token='tok')
        self.publicar(contenido='uno', idem_token='tok')
        self.assertEqual(Hilo.objects.count(), 1)

    def test_publica_aunque_redis_no_responda(self):
        """Con Redis caído, django-redis (IGNORE_EXCEPTIONS) devuelve None en add(): no es un duplicado."""
        with mock.patch('foro.views.cache.add', return_value=None):
            self.publicar(contenido='con redis caido', idem_token='tok', imagen=[imagen_png()])
        self.assertTrue(Hilo.objects.filter(contenido='con redis caido').exists())

    def test_error_htmx_devuelve_status_y_toast(self):
        respuesta = self.client.post(reverse('inicio'), {'contenido': ''}, HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('mostrarError', json.loads(respuesta['HX-Trigger']))

    def test_htmx_devuelve_tarjeta(self):
        respuesta = self.client.post(reverse('inicio'), {'contenido': 'por htmx'}, HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'por htmx')

    def test_contenido_se_escapa(self):
        self.publicar(contenido='<script>alert(1)</script>')
        self.assertNotContains(self.client.get(reverse('inicio')), '<script>alert(1)</script>')


class ImagenesTest(BaseForoTest):
    def foto(self, ancho, alto, formato='JPEG'):
        buffer = io.BytesIO()
        Image.new('RGB', (ancho, alto), 'green').save(buffer, formato)
        return SimpleUploadedFile(f'foto.{formato.lower()}', buffer.getvalue())

    def test_se_reducen_a_1600px_manteniendo_proporcion(self):
        self.client.post(reverse('inicio'), {'contenido': 'grande', 'imagen': [self.foto(4000, 3000)]})
        hilo = Hilo.objects.get()
        with Image.open(hilo.imagen.path) as img:
            self.assertEqual(img.size, (1600, 1200))

    def test_imagen_pequena_no_se_agranda(self):
        self.client.post(reverse('inicio'), {'contenido': 'chica', 'imagen': [self.foto(800, 600, 'PNG')]})
        with Image.open(Hilo.objects.get().imagen.path) as img:
            self.assertEqual(img.size, (800, 600))

    def test_avatar_a_512px(self):
        self.client.post(reverse('actualizar_avatar'), {'avatar': self.foto(2000, 2000)})
        self.ana.refresh_from_db()
        with Image.open(self.ana.avatar.path) as img:
            self.assertEqual(img.size, (512, 512))

    def test_cuatro_imagenes_se_suben_y_asignan(self):
        self.client.post(reverse('inicio'), {'contenido': 'cuatro', 'imagen': [self.foto(100, 100) for _ in range(4)]})
        hilo = Hilo.objects.get()
        nombres = [getattr(hilo, c).name for c in ('imagen', 'imagen2', 'imagen3', 'imagen4')]
        self.assertEqual(len(set(nombres)), 4)
        for nombre in nombres:
            self.assertTrue(hilo.imagen.storage.exists(nombre))

    def test_si_falla_la_bd_se_borran_las_imagenes_subidas(self):
        storage = Hilo._meta.get_field('imagen').storage
        antes = set(storage.listdir('hilos/imagenes')[1]) if storage.exists('hilos/imagenes') else set()
        with mock.patch.object(Hilo, 'save', side_effect=RuntimeError('BD caída')):
            respuesta = self.client.post(reverse('inicio'), {'contenido': 'x', 'imagen': [self.foto(100, 100)]},
                                         HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 500)
        self.assertEqual(set(storage.listdir('hilos/imagenes')[1]), antes)


class ConsultasTest(BaseForoTest):
    """El número de consultas no debe crecer con el número de elementos (sin N+1)."""

    def consultas(self, url):
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(url).status_code, 200)
        return len(ctx)

    def crear_contenido(self, n):
        for _ in range(n):
            hilo = Hilo.objects.create(titulo='t', contenido='c', autor=self.bob, universidad=self.uni)
            Respuesta.objects.create(hilo=hilo, autor=self.ana, contenido='r')
            sugerencia = Sugerencia.objects.create(usuario=self.bob, contenido='s')
            sugerencia.likes.add(self.ana)

    def test_inicio_sugerencias_y_perfil_sin_n_mas_1(self):
        self.crear_contenido(2)
        urls = ['/', '/sugerencias/', '/perfil/bob/']
        for url in urls:
            self.consultas(url)  # calienta la caché de universidades
        antes = {u: self.consultas(u) for u in urls}
        self.crear_contenido(8)
        despues = {u: self.consultas(u) for u in antes}
        self.assertEqual(antes, despues)

    def test_contador_de_respuestas_ignora_inactivas(self):
        hilo = Hilo.objects.create(titulo='t', contenido='c', autor=self.bob)
        Respuesta.objects.create(hilo=hilo, autor=self.ana, contenido='visible')
        Respuesta.objects.create(hilo=hilo, autor=self.ana, contenido='oculta', activo=False)
        self.assertEqual(Hilo.objects.con_conteos().get(pk=hilo.pk).conteo_respuestas, 1)


class DetalleYComentariosTest(BaseForoTest):
    def setUp(self):
        super().setUp()
        self.hilo = Hilo.objects.create(titulo='t', contenido='c', autor=self.ana)

    def test_comentar_notifica_al_autor(self):
        self.como(self.bob)
        self.client.post(reverse('detalle_hilo', args=[self.hilo.public_id]), {'contenido': 'buen hilo'})
        self.assertTrue(Notificacion.objects.filter(destinatario=self.ana, tipo='comentario').exists())
        respuesta = Respuesta.objects.get()
        self.assertEqual(self.client.get(reverse('detalle_respuesta', args=[respuesta.public_id])).status_code, 200)

    def test_respuesta_de_hilo_oculto_da_404(self):
        respuesta = Respuesta.objects.create(hilo=self.hilo, autor=self.bob, contenido='r')
        Hilo.objects.filter(pk=self.hilo.pk).update(activo=False)
        self.assertEqual(self.client.get(reverse('detalle_respuesta', args=[respuesta.public_id])).status_code, 404)


class LikesTest(BaseForoTest):
    def test_like_y_quitar_like_de_hilo(self):
        hilo = Hilo.objects.create(titulo='t', contenido='c', autor=self.ana)
        self.como(self.bob)
        self.assertEqual(self.client.get(reverse('boton_like', args=[hilo.id])).status_code, 405)

        self.client.post(reverse('boton_like', args=[hilo.id]))
        hilo.refresh_from_db()
        self.assertEqual(hilo.likes_count, 1)
        self.assertTrue(Notificacion.objects.filter(destinatario=self.ana, tipo='like_hilo').exists())

        self.client.post(reverse('boton_like', args=[hilo.id]))
        hilo.refresh_from_db()
        self.assertEqual(hilo.likes_count, 0)
        self.assertFalse(Notificacion.objects.filter(destinatario=self.ana, tipo='like_hilo').exists())

    def test_like_respuesta(self):
        hilo = Hilo.objects.create(titulo='t', contenido='c', autor=self.ana)
        respuesta = Respuesta.objects.create(hilo=hilo, autor=self.ana, contenido='r')
        self.como(self.bob)
        self.assertContains(self.client.post(reverse('like_respuesta', args=[respuesta.id])), 'text-red-500')
        self.assertEqual(respuesta.likes.count(), 1)


class NotificacionesTest(BaseForoTest):
    def test_pagina_completa_sin_htmx(self):
        """Antes daba 500 (TemplateDoesNotExist)."""
        respuesta = self.client.get(reverse('notificaciones'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTemplateUsed(respuesta, 'foro/notificaciones.html')

    def test_panel_htmx_marca_leidas(self):
        Notificacion.objects.create(destinatario=self.ana, tipo='seguidor').actores.add(self.bob)
        respuesta = self.client.get(reverse('notificaciones'), HTTP_HX_REQUEST='true')
        self.assertTemplateUsed(respuesta, 'foro/partials/notificaciones_lista.html')
        self.assertFalse(Notificacion.objects.filter(leido=False).exists())

    def test_tarjeta_de_notificacion_ajena_da_404(self):
        notif = Notificacion.objects.create(destinatario=self.ana, tipo='seguidor')
        self.como(self.bob)
        self.assertEqual(self.client.get(reverse('obtener_tarjeta_notificacion', args=[notif.id])).status_code, 404)

    def test_estado_tiempo_real(self):
        Notificacion.objects.create(destinatario=self.ana, tipo='seguidor')
        mensaje = Mensaje.objects.create(remitente=self.bob, destinatario=self.ana, contenido='hola')
        datos = self.client.get(reverse('estado_tiempo_real')).json()
        self.assertEqual(datos, {'notificaciones': 1, 'mensajes': 1, 'ultimo_mensaje_id': mensaje.id})

    def test_badge_de_mensajes_en_contexto(self):
        Mensaje.objects.create(remitente=self.bob, destinatario=self.ana, contenido='hola')
        self.assertEqual(self.client.get(reverse('inicio')).context['total_mensajes_sin_leer'], 1)


class SugerenciasTest(BaseForoTest):
    def setUp(self):
        super().setUp()
        self.sugerencia = Sugerencia.objects.create(usuario=self.ana, contenido='mejorar X')

    def interactuar(self, accion):
        return self.client.post(reverse('interaccion_sugerencia', args=[self.sugerencia.public_id, accion]))

    def test_crear_y_limite_de_longitud(self):
        self.client.post(reverse('sugerencias'), {'contenido': 'nueva'})
        self.client.post(reverse('sugerencias'), {'contenido': 'x' * 1001})
        self.assertEqual(Sugerencia.objects.count(), 2)

    def test_botones_like_son_formularios_post(self):
        """Antes eran <a href> (GET) contra una vista que exige POST -> 405."""
        html = self.client.get(reverse('sugerencias')).content.decode()
        url_like = reverse('interaccion_sugerencia', args=[self.sugerencia.public_id, 'like'])
        self.assertIn(f'action="{url_like}"', html)
        self.assertNotIn(f'href="{url_like}"', html)

    def test_like_dislike(self):
        self.como(self.bob)
        self.interactuar('like')
        self.assertTrue(self.sugerencia.likes.filter(pk=self.bob.pk).exists())
        self.interactuar('dislike')
        self.assertFalse(self.sugerencia.likes.filter(pk=self.bob.pk).exists())
        self.assertTrue(self.sugerencia.dislikes.filter(pk=self.bob.pk).exists())
        self.assertEqual(self.interactuar('hack').status_code, 404)

    def test_like_unlike_no_duplica_notificaciones(self):
        self.como(self.bob)
        for _ in range(3):
            self.interactuar('like')
            Notificacion.objects.update(leido=True)
            self.interactuar('like')
        self.interactuar('like')
        self.assertEqual(Notificacion.objects.filter(tipo='like_sug').count(), 1)

    def test_quitar_like_retira_notificacion(self):
        self.como(self.bob)
        self.interactuar('like')
        self.interactuar('like')
        self.assertFalse(Notificacion.objects.filter(tipo='like_sug').exists())

    def test_comentar_con_notificaciones_duplicadas_no_revienta(self):
        """Antes: MultipleObjectsReturned (500) con get_or_create(..., leido=False)."""
        for _ in range(2):
            Notificacion.objects.create(destinatario=self.ana, tipo='coment_sug', sugerencia=self.sugerencia)
        self.como(self.bob)
        respuesta = self.client.post(reverse('detalle_sugerencia', args=[self.sugerencia.public_id]), {'contenido': 'si'})
        self.assertEqual(respuesta.status_code, 302)

    def test_hilos_de_respuestas(self):
        self.como(self.bob)
        url = reverse('detalle_sugerencia', args=[self.sugerencia.public_id])
        self.client.post(url, {'contenido': 'primera'})
        padre = RespuestaSugerencia.objects.get()
        self.como(self.ana)
        self.client.post(url, {'contenido': 'respuesta', 'respuesta_padre_id': padre.id})
        self.assertEqual(padre.respuestas_hijas.count(), 1)
        self.assertEqual(self.client.post(url, {'contenido': 'x', 'respuesta_padre_id': 'abc'}).status_code, 404)
        self.assertEqual(self.client.get(reverse('detalle_respuesta_sugerencia', args=[padre.id])).status_code, 200)
        self.client.post(reverse('like_respuesta_sugerencia', args=[padre.id]))
        self.assertEqual(padre.likes.count(), 1)


class EditarEliminarTest(BaseForoTest):
    def setUp(self):
        super().setUp()
        self.hilo = Hilo.objects.create(titulo='t', contenido='original', autor=self.ana)

    def test_solo_el_autor(self):
        self.como(self.bob)
        self.assertEqual(self.client.get(reverse('editar_hilo', args=[self.hilo.public_id])).status_code, 404)
        self.assertEqual(self.client.post(reverse('eliminar_hilo', args=[self.hilo.public_id])).status_code, 404)
        self.assertTrue(Hilo.objects.filter(pk=self.hilo.pk).exists())

    def test_editar_y_eliminar(self):
        url = reverse('editar_hilo', args=[self.hilo.public_id])
        self.client.post(url, {'contenido': '  editado  '})
        self.hilo.refresh_from_db()
        self.assertEqual(self.hilo.contenido, 'editado')
        self.assertEqual(self.client.post(url, {'contenido': 'y' * 600}).status_code, 200)

        self.client.post(reverse('eliminar_hilo', args=[self.hilo.public_id]))
        self.assertFalse(Hilo.objects.filter(pk=self.hilo.pk).exists())


@override_settings(REPORTES_PARA_OCULTAR=3, REPORTES_ANTIGUEDAD_MINIMA=timedelta(days=3))
class ReportesTest(BaseForoTest):
    def setUp(self):
        super().setUp()
        self.hilo = Hilo.objects.create(titulo='t', contenido='reportame', autor=self.bob)

    def reportar(self, usuario):
        self.como(usuario)
        return self.client.post(reverse('reportar_hilo', args=[self.hilo.public_id]))

    def crear_cuentas(self, n, antiguedad_dias):
        cuentas = []
        for i in range(n):
            u = UsuarioForo.objects.create_user(f'rep{antiguedad_dias}_{i}', password='x')
            UsuarioForo.objects.filter(pk=u.pk).update(date_joined=timezone.now() - timedelta(days=antiguedad_dias))
            cuentas.append(u)
        return cuentas

    def test_el_hilo_reportado_desaparece_para_quien_reporta(self):
        respuesta = self.reportar(self.ana)
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotContains(self.client.get(reverse('inicio')), 'reportame')
        self.como(self.bob)
        self.assertContains(self.client.get(reverse('inicio')), 'reportame')

    def test_cuentas_nuevas_no_ocultan_hilos(self):
        for u in self.crear_cuentas(5, antiguedad_dias=0):
            self.reportar(u)
        self.hilo.refresh_from_db()
        self.assertTrue(self.hilo.activo)

    def test_cuentas_antiguas_ocultan_al_llegar_al_umbral(self):
        for u in self.crear_cuentas(3, antiguedad_dias=10):
            self.reportar(u)
        self.hilo.refresh_from_db()
        self.assertFalse(self.hilo.activo)

    def test_no_puedes_reportar_tu_propio_hilo(self):
        self.reportar(self.bob)
        self.assertFalse(self.hilo.reportes.exists())

    def test_limite_de_reportes(self):
        self.como(self.ana)
        for i in range(21):
            h = Hilo.objects.create(titulo='t', contenido='c', autor=self.bob)
            respuesta = self.client.post(reverse('reportar_hilo', args=[h.public_id]), HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 429)
