#!/bin/sh

python manage.py collectstatic --noinput
python manage.py migrate --noinput
gunicorn --bind 0.0.0.0:8000 --workers 3 ala_el_8ahwa.wsgi:application

