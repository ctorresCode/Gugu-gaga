"""
Configuración de gunicorn para producción. Gunicorn la carga automáticamente desde el
directorio de trabajo; los parámetros que se pasen en el comando de arranque tienen prioridad.
"""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# Procesos x hilos = peticiones atendidas a la vez. Con hilos, mientras una petición espera a la
# BD, a Redis o a R2, otra puede avanzar. Ajustable con variables de entorno según el plan.
workers = int(os.environ.get('WEB_CONCURRENCY', 2))
threads = int(os.environ.get('GUNICORN_THREADS', 4))
worker_class = 'gthread'

timeout = 60            # subidas de imágenes en conexiones lentas
keepalive = 5           # reutiliza conexiones del proxy
max_requests = 1000     # recicla procesos para evitar que crezca la memoria
max_requests_jitter = 100
