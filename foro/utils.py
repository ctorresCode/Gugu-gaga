import logging
import uuid
from io import BytesIO

from django.core.files.base import ContentFile
from django.utils.http import url_has_allowed_host_and_scheme
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

MAX_TITULO = 200
MAX_HILO = 500
MAX_COMENTARIO = 1000
MAX_SUGERENCIA = 1000
MAX_MENSAJE = 1000

FORMATOS_PERMITIDOS = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}
MAX_PIXELES = 25_000_000  


def es_htmx(request):
    return bool(request.headers.get('HX-Request')) or request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def referer_seguro(request, default='/'):
    referer = request.META.get('HTTP_REFERER', default)
    if not url_has_allowed_host_and_scheme(url=referer, allowed_hosts={request.get_host()}):
        return default
    return referer

def a_int(valor, default=None):
    """int() que nunca revienta (None, letras, unicode raro o números gigantes)."""
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return default
    if abs(numero) > 2_147_483_647:
        return default
    return numero

def limpiar_texto(valor, max_len, requerido=True, nombre='El contenido'):
    """Devuelve (texto_limpio, error). error es None si todo está bien."""
    texto = (valor or '').strip()
    if not texto:
        return '', (f'{nombre} no puede estar vacío.' if requerido else None)
    if len(texto) > max_len:
        return texto, f'{nombre} no puede superar los {max_len} caracteres.'
    return texto, None

def validar_imagen(archivo, max_mb=5):
    """Devuelve un mensaje de error (str) o None si la imagen es válida."""
    if archivo.size > max_mb * 1024 * 1024:
        return f'La imagen excede los {max_mb}MB permitidos.'

    try:
        img = Image.open(archivo)
        formato = img.format
        ancho, alto = img.size
        img.verify()
    except Image.DecompressionBombError:
        return 'La imagen es demasiado grande en dimensiones.'
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        return 'El archivo no es una imagen válida o está corrupto.'
    finally:
        archivo.seek(0)

    if formato not in FORMATOS_PERMITIDOS:
        return 'Formato no permitido. Usa JPG, PNG o WEBP.'
    if ancho * alto > MAX_PIXELES:
        return 'La imagen es demasiado grande en dimensiones.'
    return None

def limpiar_imagen(archivo):
    """
    Re-codifica la imagen: quita EXIF (GPS, cámara, etc.), aplica la rotación real
    y le pone un nombre nuevo (uuid) con la extensión correcta según el formato verificado.
    Llamar SOLO después de validar_imagen().
    """
    archivo.seek(0)
    original = Image.open(archivo)
    formato = original.format
    if formato not in FORMATOS_PERMITIDOS:
        raise ValueError('Formato no permitido')

    img = ImageOps.exif_transpose(original)
    for clave in ('exif', 'xmp', 'XML:com.adobe.xmp', 'comment'):
        img.info.pop(clave, None)

    opciones = {}
    if formato == 'JPEG':
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        opciones = {'quality': 88, 'optimize': True, 'exif': b''}
    elif formato == 'WEBP':
        opciones = {'quality': 88, 'exif': b''}
    elif formato == 'PNG':
        opciones = {'optimize': True}

    buffer = BytesIO()
    img.save(buffer, format=formato, **opciones)
    nombre = f'{uuid.uuid4().hex}.{FORMATOS_PERMITIDOS[formato]}'
    return ContentFile(buffer.getvalue(), name=nombre)

def procesar_imagenes(archivos, max_mb=5):
    """
    Valida y limpia una lista de archivos.
    Devuelve (lista_de_archivos_limpios, error). Si hay error, la lista es None.
    """
    limpios = []
    for archivo in archivos:
        error = validar_imagen(archivo, max_mb=max_mb)
        if error:
            return None, error
        try:
            limpios.append(limpiar_imagen(archivo))
        except Exception:
            logger.exception('No se pudo procesar una imagen subida')
            return None, 'No se pudo procesar la imagen. Prueba con otra.'
    return limpios, None