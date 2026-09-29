"""
Cierra el acceso de la API pública de Supabase (roles `anon` / `authenticated`) a la base de datos.

Supabase expone el esquema `public` por REST y Realtime usando la anon key, que va en el HTML.
Las tablas que crea Django no tenían RLS ni permisos restringidos, así que cualquiera podía leer
(y modificar) usuarios, sesiones y mensajes privados.

Después de esta migración:
  * anon/authenticated no tienen NINGÚN permiso en `public` (tampoco en tablas futuras).
  * Todas las tablas tienen RLS activado (Django se conecta como dueño de las tablas, no le afecta).
  * Para el tiempo real del foro, anon solo puede leer columnas identificadoras (ids y FKs) de las
    tablas públicas del foro, y solo de filas activas. Nunca contenido, emails, hashes ni mensajes.
  * Mensajes y notificaciones salen de la publicación de Realtime: la web los consulta a Django
    (endpoint /estado/) con la sesión del usuario.

Solo se ejecuta en PostgreSQL con los roles de Supabase; en SQLite/tests no hace nada.
"""
from django.db import migrations

# tabla -> (columnas legibles por anon, condición RLS)
LECTURA_TIEMPO_REAL = {
    'foro_hilo': (('id', 'autor_id', 'activo'), 'activo'),
    'foro_respuesta': (('id', 'hilo_id', 'autor_id', 'respuesta_padre_id', 'activo'), 'activo'),
    'foro_hilo_likes': (('id', 'hilo_id', 'usuarioforo_id'), 'true'),
    'foro_respuesta_likes': (('id', 'respuesta_id', 'usuarioforo_id'), 'true'),
    'foro_sugerencia': (('id', 'usuario_id'), 'true'),
    'foro_sugerencia_likes': (('id', 'sugerencia_id', 'usuarioforo_id'), 'true'),
    'foro_sugerencia_dislikes': (('id', 'sugerencia_id', 'usuarioforo_id'), 'true'),
    'foro_respuestasugerencia': (('id', 'sugerencia_id', 'respuesta_padre_id', 'autor_id'), 'true'),
    'foro_respuestasugerencia_likes': (('id', 'respuestasugerencia_id', 'usuarioforo_id'), 'true'),
}

TABLAS_PRIVADAS_REALTIME = ('usuarios_mensaje', 'foro_notificacion')

POLITICA = 'tiempo_real_lectura_ids'


def _roles_supabase_existen(cursor):
    cursor.execute("SELECT count(*) FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
    return cursor.fetchone()[0] == 2


def asegurar(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        if not _roles_supabase_existen(cursor):
            return

        cursor.execute("""
            REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
            REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
            ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
            ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;

            DO $$
            DECLARE t record;
            BEGIN
                FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
                    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.tablename);
                    -- revoca también permisos por columna que pudieran existir
                    EXECUTE format(
                        'REVOKE SELECT (%s) ON public.%I FROM anon, authenticated',
                        (SELECT string_agg(quote_ident(attname), ', ')
                           FROM pg_attribute
                          WHERE attrelid = format('public.%I', t.tablename)::regclass
                            AND attnum > 0 AND NOT attisdropped),
                        t.tablename
                    );
                END LOOP;
            END $$;
        """)

        for tabla, (columnas, condicion) in LECTURA_TIEMPO_REAL.items():
            cols = ', '.join(columnas)
            cursor.execute(f"""
                GRANT SELECT ({cols}) ON public.{tabla} TO anon;
                DROP POLICY IF EXISTS {POLITICA} ON public.{tabla};
                CREATE POLICY {POLITICA} ON public.{tabla} FOR SELECT TO anon USING ({condicion});
            """)

        # Sacar tablas privadas de Realtime. Puede requerir ser dueño de la publicación:
        # si no hay permiso, no rompemos el deploy (RLS ya impide que anon las reciba).
        for tabla in TABLAS_PRIVADAS_REALTIME:
            cursor.execute(f"""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_publication_tables
                                WHERE pubname = 'supabase_realtime' AND schemaname = 'public'
                                  AND tablename = '{tabla}') THEN
                        ALTER PUBLICATION supabase_realtime DROP TABLE public.{tabla};
                    END IF;
                EXCEPTION WHEN insufficient_privilege THEN
                    RAISE NOTICE 'Sin permiso para quitar {tabla} de supabase_realtime';
                END $$;
            """)


class Migration(migrations.Migration):

    dependencies = [
        ('foro', '0020_quitar_respuestas_count'),
        ('usuarios', '0013_verificacion_email'),
        ('axes', '__latest__'),
        ('sessions', '__first__'),
        ('admin', '__latest__'),
    ]

    operations = [
        migrations.RunPython(asegurar, migrations.RunPython.noop),
    ]
