from django.db import migrations, models


def carry_read_state_forward(apps, schema_editor):
    Notification = apps.get_model("notifications", "Notification")

    carried = Notification.objects.filter(is_read=True).count()
    if carried:
        for notification in Notification.objects.filter(is_read=True).iterator():
            Notification.objects.filter(pk=notification.pk).update(
                read_at=notification.created_at
            )
        print(
            f"  notifications.0003: carried {carried} read notification(s) to "
            f"read_at=created_at; the real read time was never recorded"
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0002_alter_notification_notification_type"),
    ]

    operations = [
        migrations.RenameField(
            model_name="notification",
            old_name="notification_type",
            new_name="kind",
        ),
        migrations.AddField(
            model_name="notification",
            name="read_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(carry_read_state_forward, noop),
        migrations.RemoveField(
            model_name="notification",
            name="is_read",
        ),
    ]
