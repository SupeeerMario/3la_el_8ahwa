import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ala_el_8ahwa.settings")

app = Celery("ala_el_8ahwa")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
