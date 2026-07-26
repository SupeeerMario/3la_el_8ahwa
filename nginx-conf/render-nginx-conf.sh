#!/bin/sh
set -eu

: "${DJANGO_UPSTREAM:?DJANGO_UPSTREAM must be set to the Django app service name (e.g. django-app-local or django-app-prod)}"

envsubst '${DJANGO_UPSTREAM}' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf
