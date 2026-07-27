import django.db.models.functions.text
from django.db import migrations, models


def normalize_and_free_duplicate_emails(apps, schema_editor):
    User = apps.get_model("users", "User")

    blanked = User.objects.filter(email="").update(email=None)
    if blanked:
        print(f"  users_user: {blanked} blank email(s) normalized to NULL")

    kept = {}
    for user in User.objects.exclude(email=None).order_by("id").iterator():
        key = user.email.lower()
        if key in kept:
            print(
                f"  users_user id={user.id}: email {user.email!r} cleared "
                f"(duplicate of id={kept[key]}, which keeps it)"
            )
            User.objects.filter(pk=user.pk).update(email=None)
        else:
            kept[key] = user.id


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('users', '0002_user_display_name'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='email',
            field=models.EmailField(blank=True, max_length=254, null=True, verbose_name='email address'),
        ),
        migrations.RunPython(
            normalize_and_free_duplicate_emails,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.UniqueConstraint(django.db.models.functions.text.Lower('email'), condition=models.Q(('email__isnull', False)), name='unique_user_email_ci'),
        ),
    ]
