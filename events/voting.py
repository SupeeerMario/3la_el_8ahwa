import random

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from .models import Event


def tally(event):
    return event.locations.annotate(vote_count=Count("votes")).order_by(
        "-vote_count", "id"
    )


def voting_open(event):
    return timezone.now() < event.start_time and not event.winner_frozen


def freeze_winner(event_id):
    with transaction.atomic():
        try:
            event = Event.objects.select_for_update().get(pk=event_id)
        except Event.DoesNotExist:
            return None

        if event.winner_frozen:
            return event

        ranked = list(tally(event))
        top = ranked[0].vote_count if ranked else 0

        winner = None
        if top > 0:
            winner = random.choice([loc for loc in ranked if loc.vote_count == top])

        event.winning_location = winner
        event.winner_frozen = True
        event.save(update_fields=["winning_location", "winner_frozen"])

    from groups.room import voting_closed

    voting_closed(event)
    return event


def due_event_ids():
    return list(
        Event.objects.filter(
            start_time__lte=timezone.now(), winner_frozen=False
        ).values_list("id", flat=True)
    )


def freeze_due_winners():
    frozen = 0
    for event_id in due_event_ids():
        if freeze_winner(event_id) is not None:
            frozen += 1
    return frozen
