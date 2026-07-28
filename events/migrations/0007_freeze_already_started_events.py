from django.db import migrations
from django.db.models import Count
from django.utils import timezone


def freeze_already_started_events(apps, schema_editor):
    Event = apps.get_model("events", "Event")

    frozen = 0
    with_winner = 0

    for event in Event.objects.filter(
        start_time__lte=timezone.now(), winner_frozen=False
    ):
        ranked = list(
            event.locations.annotate(vote_count=Count("votes")).order_by(
                "-vote_count", "id"
            )
        )
        winner = ranked[0] if ranked and ranked[0].vote_count > 0 else None

        Event.objects.filter(pk=event.pk).update(
            winner_frozen=True, winning_location=winner
        )

        frozen += 1
        if winner is not None:
            with_winner += 1

    if frozen:
        print(
            f"  events.0007: froze {frozen} event(s) that had already started "
            f"({with_winner} with a winner, {frozen - with_winner} with no votes)"
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0006_locationvote_event_unique_vote_per_event"),
    ]

    operations = [
        migrations.RunPython(freeze_already_started_events, noop),
    ]
