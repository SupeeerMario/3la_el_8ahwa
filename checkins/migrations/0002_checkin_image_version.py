from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("checkins", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="checkin",
            name="image_version",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
    ]
