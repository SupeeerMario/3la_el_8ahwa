from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0002_groupinvitetoken"),
    ]

    operations = [
        migrations.AddField(
            model_name="group",
            name="image_version",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
    ]
