#!/usr/bin/env bash
# Salir si hay algún error
set -o errexit

# Instalar las librerías del requirements.txt
pip install -r requirements.txt

# Recopilar los archivos estáticos (CSS, JS, Tailwind)
python manage.py collectstatic --no-input

# Aplicar las migraciones a la base de datos
python manage.py migrate