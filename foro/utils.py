import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
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
MAX_LADO = 1600       # px del lado mayor: suficiente para verse nítido en el feed y el visor
MAX_LADO_AVATAR = 512


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

def limpiar_imagen(archivo, max_lado=MAX_LADO):
    """
    Re-codifica la imagen: quita EXIF (GPS, cámara, etc.), aplica la rotación real,
    la reduce a `max_lado` px como máximo y le pone un nombre nuevo (uuid) con la
    extensión correcta según el formato verificado. Llamar SOLO después de validar_imagen().
    """
    archivo.seek(0)
    original = Image.open(archivo)
    formato = original.format
    if formato not in FORMATOS_PERMITIDOS:
        raise ValueError('Formato no permitido')

    img = ImageOps.exif_transpose(original)
    if max(img.size) > max_lado:
        img.thumbnail((max_lado, max_lado), Image.Resampling.LANCZOS)
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
        opciones = {'compress_level': 6}  # optimize=True tarda muchísimo en PNG grandes

    buffer = BytesIO()
    img.save(buffer, format=formato, **opciones)
    nombre = f'{uuid.uuid4().hex}.{FORMATOS_PERMITIDOS[formato]}'
    return ContentFile(buffer.getvalue(), name=nombre)

def procesar_imagenes(archivos, max_mb=5, max_lado=MAX_LADO):
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
            limpios.append(limpiar_imagen(archivo, max_lado=max_lado))
        except Exception:
            logger.exception('No se pudo procesar una imagen subida')
            return None, 'No se pudo procesar la imagen. Prueba con otra.'
    return limpios, None


def asignar_imagenes_en_paralelo(instancia, campos, archivos):
    """
    Sube los archivos al storage (R2) EN PARALELO y asigna los nombres resultantes a los
    campos de la instancia, así el save() posterior no los vuelve a subir uno por uno.
    Devuelve una función para borrar lo subido si luego falla el guardado en la BD.
    """
    pendientes = []
    for campo, archivo in zip(campos, archivos):
        field = instancia._meta.get_field(campo)
        pendientes.append((campo, field.storage, field.generate_filename(instancia, archivo.name), archivo))

    def subir(item):
        _, storage, nombre, archivo = item
        return storage.save(nombre, archivo, max_length=255)

    if len(pendientes) > 1:
        # S3Storage usa una conexión por hilo, así que es seguro en paralelo.
        with ThreadPoolExecutor(max_workers=len(pendientes)) as ejecutor:
            nombres = list(ejecutor.map(subir, pendientes))
    else:
        nombres = [subir(p) for p in pendientes]

    for (campo, _, _, _), nombre in zip(pendientes, nombres):
        setattr(instancia, campo, nombre)

    def deshacer():
        for (_, storage, _, _), nombre in zip(pendientes, nombres):
            try:
                storage.delete(nombre)
            except Exception:
                logger.exception('No se pudo borrar %s tras un error', nombre)

    return deshacer
