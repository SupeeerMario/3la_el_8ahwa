from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0007_freeze_already_started_events"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="reminder_sent",
            field=models.BooleanField(default=False),
        ),
    ]
