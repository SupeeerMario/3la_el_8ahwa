from django.db import migrations, models
import django.db.models.deletion


def populate_event_and_dedupe(apps, schema_editor):
    LocationVote = apps.get_model("events", "LocationVote")

    for vote in LocationVote.objects.select_related("location").iterator():
        LocationVote.objects.filter(pk=vote.pk).update(event_id=vote.location.event_id)

    seen = set()
    duplicates = []
    for pk, event_id, voted_by_id in LocationVote.objects.order_by("pk").values_list(
        "pk", "event_id", "voted_by_id"
    ):
        key = (event_id, voted_by_id)
        if key in seen:
            duplicates.append(pk)
        else:
            seen.add(key)

    if duplicates:
        LocationVote.objects.filter(pk__in=duplicates).delete()
        print(
            f"  events.0006: dropped {len(duplicates)} duplicate vote(s); "
            f"kept the earliest vote per (event, user)"
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0005_eventlocation_locationvote_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="winner_frozen",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="locationvote",
            name="event",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="votes",
                to="events.event",
            ),
        ),
        migrations.RunPython(populate_event_and_dedupe, noop),
        migrations.AlterField(
            model_name="locationvote",
            name="event",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="votes",
                to="events.event",
            ),
        ),
        migrations.AddConstraint(
            model_name="locationvote",
            constraint=models.UniqueConstraint(
                fields=("event", "voted_by"), name="unique_vote_per_event"
            ),
        ),
    ]
