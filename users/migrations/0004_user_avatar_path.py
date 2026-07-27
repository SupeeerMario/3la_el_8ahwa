from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_alter_user_email_user_unique_user_email_ci'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='avatar_path',
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
