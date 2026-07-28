from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from notifications.services import notify_group
from .models import Event


def due_reminder_event_ids():
    lead = timedelta(minutes=settings.EVENT_REMINDER_LEAD_MINUTES)
    now = timezone.now()

    return list(
        Event.objects.filter(
            reminder_sent=False,
            start_time__gt=now,
            start_time__lte=now + lead,
        ).values_list("id", flat=True)
    )


def send_reminder(event_id):
    with transaction.atomic():
        try:
            event = Event.objects.select_for_update().select_related("group").get(
                pk=event_id
            )
        except Event.DoesNotExist:
            return None

        if event.reminder_sent:
            return event

        event.reminder_sent = True
        event.save(update_fields=["reminder_sent"])

    notify_group(
        event.group,
        "event_reminder",
        {
            "event_id": event.id,
            "event_title": event.title,
            "group_id": event.group_id,
            "group_name": event.group.name,
            "start_time": event.start_time.isoformat(),
        },
    )

    return event


def send_due_reminders():
    sent = 0
    for event_id in due_reminder_event_ids():
        if send_reminder(event_id) is not None:
            sent += 1
    return sent
