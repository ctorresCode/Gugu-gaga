import io
import re
import shutil

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from config.utils import get_client_ip
from usuarios.models import Mensaje, Universidad, UsuarioForo


def tearDownModule():
    shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)


def imagen_png():
    buffer = io.BytesIO()
    Image.new('RGB', (20, 20), 'blue').save(buffer, 'PNG')
    return SimpleUploadedFile('a.png', buffer.getvalue(), content_type='image/png')


class BaseUsuariosTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.uni = Universidad.objects.create(nombre='UASD')
        cls.ana = UsuarioForo.objects.create_user('ana', password='Xk9!mPq2zL', universidad=cls.uni)
        cls.bob = UsuarioForo.objects.create_user('bob', password='Xk9!mPq2zL', universidad=cls.uni)

    def setUp(self):
        cache.clear()


class EmailTest(BaseUsuariosTest):
    def test_varios_usuarios_sin_email(self):
        """Antes: IntegrityError al crear el segundo usuario sin email ('' duplicado en campo unique)."""
        UsuarioForo.objects.create_user('c1', password='x')
        UsuarioForo.objects.create_user('c2', password='x')
        self.assertEqual(UsuarioForo.objects.filter(email__isnull=True).count(), 4)

    def test_email_se_normaliza(self):
        u = UsuarioForo.objects.create_user('c3', email='  Mi@Correo.COM ', password='x')
        self.assertEqual(u.email, 'mi@correo.com')


class RegistroLoginTest(BaseUsuariosTest):
    def test_registro(self):
        datos = {'username': 'nuevo', 'universidad': self.uni.id, 'password1': 'Xk9!mPq2zL',
                 'password2': 'Xk9!mPq2zL', 'mayor_edad': 'on', 'consentimiento': 'on'}
        self.assertEqual(self.client.post(reverse('registro'), datos).status_code, 302)
        nuevo = UsuarioForo.objects.get(username='nuevo')
        self.assertIsNone(nuevo.email)
        self.assertTrue(nuevo.acepto_terminos_version)

    def test_registro_sin_consentimiento(self):
        datos = {'username': 'nuevo', 'universidad': self.uni.id, 'password1': 'Xk9!mPq2zL', 'password2': 'Xk9!mPq2zL'}
        self.client.post(reverse('registro'), datos)
        self.assertFalse(UsuarioForo.objects.filter(username='nuevo').exists())

    def test_login_por_formulario(self):
        respuesta = self.client.post(reverse('login'), {'username': 'ana', 'password': 'Xk9!mPq2zL'})
        self.assertEqual(respuesta.status_code, 302)

    def test_logout_solo_por_post(self):
        self.client.force_login(self.ana)
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        self.assertEqual(self.client.get(reverse('inicio')).status_code, 200)  # sigue dentro
        self.client.post(reverse('logout'))
        self.assertEqual(self.client.get(reverse('inicio')).status_code, 302)


class IpClienteTest(TestCase):
    def peticion(self, **meta):
        return RequestFactory().get('/', **meta)

    @override_settings(PROXY_COUNT=1, BEHIND_CLOUDFLARE=False)
    def test_ignora_ips_falsas_en_x_forwarded_for(self):
        req = self.peticion(REMOTE_ADDR='10.0.0.1', HTTP_X_FORWARDED_FOR='6.6.6.6, 203.0.113.7')
        self.assertEqual(get_client_ip(req), '203.0.113.7')

    @override_settings(PROXY_COUNT=0, BEHIND_CLOUDFLARE=False)
    def test_sin_proxy_usa_remote_addr(self):
        req = self.peticion(REMOTE_ADDR='203.0.113.7', HTTP_X_FORWARDED_FOR='6.6.6.6')
        self.assertEqual(get_client_ip(req), '203.0.113.7')

    @override_settings(PROXY_COUNT=1, BEHIND_CLOUDFLARE=True)
    def test_cloudflare(self):
        req = self.peticion(REMOTE_ADDR='10.0.0.1', HTTP_CF_CONNECTING_IP='198.51.100.9', HTTP_X_FORWARDED_FOR='6.6.6.6')
        self.assertEqual(get_client_ip(req), '198.51.100.9')

    @override_settings(PROXY_COUNT=1, BEHIND_CLOUDFLARE=False)
    def test_bloqueo_de_login_no_se_evita_con_cabecera_falsa(self):
        real = {'REMOTE_ADDR': '10.0.0.1'}
        for _ in range(8):
            self.client.post(reverse('login'), {'username': 'x', 'password': 'mala'},
                             HTTP_X_FORWARDED_FOR='203.0.113.7', **real)
        UsuarioForo.objects.create_user('x', password='Buena!123x')
        respuesta = self.client.post(reverse('login'), {'username': 'x', 'password': 'Buena!123x'},
                                     HTTP_X_FORWARDED_FOR='1.2.3.4, 203.0.113.7', **real)
        self.assertNotEqual(respuesta.get('Location'), reverse('inicio'))


class PerfilTest(BaseUsuariosTest):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.ana)

    def editar(self, **datos):
        base = {'username': 'ana', 'descripcion': ''}
        base.update(datos)
        return self.client.post(reverse('editar_perfil', args=['ana']), base)

    def test_perfil_y_seguir(self):
        self.assertEqual(self.client.get(reverse('perfil_usuario', args=['bob'])).status_code, 200)
        self.assertEqual(self.client.get(reverse('perfil_usuario', args=['nadie'])).status_code, 404)
        self.client.post(reverse('seguir_usuario', args=['bob']))
        self.assertTrue(self.ana.seguidos.filter(pk=self.bob.pk).exists())
        self.client.post(reverse('seguir_usuario', args=['ana']))
        self.assertFalse(self.ana.seguidos.filter(pk=self.ana.pk).exists())

    def test_descripcion_limitada(self):
        self.editar(descripcion='d' * 501)
        self.ana.refresh_from_db()
        self.assertFalse(self.ana.descripcion)

    def test_cambiar_email_requiere_codigo(self):
        respuesta = self.editar(email='ana@x.com')
        self.assertRedirects(respuesta, reverse('confirmar_email'))
        self.ana.refresh_from_db()
        self.assertIsNone(self.ana.email)
        self.assertEqual(self.ana.email_pendiente, 'ana@x.com')

        codigo = re.search(r'(\d{6})', mail.outbox[-1].body).group(1)
        self.client.post(reverse('confirmar_email'), {'codigo': '000000' if codigo != '000000' else '111111'})
        self.ana.refresh_from_db()
        self.assertIsNone(self.ana.email)

        self.client.post(reverse('confirmar_email'), {'codigo': codigo})
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.email, 'ana@x.com')
        self.assertIsNone(self.ana.email_pendiente)

    def test_email_en_uso(self):
        UsuarioForo.objects.filter(pk=self.bob.pk).update(email='bob@x.com')
        self.assertEqual(self.editar(email='BOB@x.com').status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_quitar_email_no_necesita_codigo(self):
        UsuarioForo.objects.filter(pk=self.ana.pk).update(email='ana@x.com')
        self.editar(email='')
        self.ana.refresh_from_db()
        self.assertIsNone(self.ana.email)

    def test_avatar(self):
        self.assertEqual(self.client.post(reverse('actualizar_avatar')).status_code, 400)
        self.assertEqual(self.client.post(reverse('actualizar_avatar'), {'avatar': imagen_png()}).status_code, 200)


class ChatTest(BaseUsuariosTest):
    def setUp(self):
        super().setUp()
        self.eve = UsuarioForo.objects.create_user('eve', password='x')
        self.ana.seguidos.add(self.bob)
        self.bob.seguidos.add(self.ana)
        self.client.force_login(self.ana)

    def test_mensajes_entre_amigos(self):
        url = reverse('chat_usuario', args=['bob'])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(url, {'contenido': 'hola'})
        self.client.post(url, {'imagen': [imagen_png()]})
        self.assertEqual(Mensaje.objects.count(), 2)
        self.assertEqual(self.client.post(url, {'contenido': ''}).status_code, 400)

    def test_no_amigos_no_pueden_escribir(self):
        self.client.force_login(self.eve)
        respuesta = self.client.post(reverse('chat_usuario', args=['bob']), {'contenido': 'spam'})
        self.assertEqual(respuesta.status_code, 403)


class ResetPasswordTest(BaseUsuariosTest):
    def test_flujo_completo(self):
        UsuarioForo.objects.filter(pk=self.ana.pk).update(email='ana@x.com')
        url = reverse('recuperar_password')
        self.client.post(url, {'accion': 'enviar_codigo', 'email': 'ANA@x.com'})
        codigo = re.search(r'(\d{6})', mail.outbox[-1].body).group(1)

        self.client.post(url, {'accion': 'verificar_codigo', 'codigo': codigo})
        respuesta = self.client.post(reverse('nueva_password'), {'password1': 'Nuev0!Segura9', 'password2': 'Nuev0!Segura9'})
        self.assertRedirects(respuesta, reverse('inicio'))
        self.ana.refresh_from_db()
        self.assertTrue(self.ana.check_password('Nuev0!Segura9'))

    def test_email_desconocido_no_revela_nada(self):
        respuesta = self.client.post(reverse('recuperar_password'), {'accion': 'enviar_codigo', 'email': 'nadie@x.com'})
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)
