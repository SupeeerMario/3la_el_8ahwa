from django.db import migrations, models

import groups.models


def fill_codes(apps, schema_editor):
    GroupInviteToken = apps.get_model("groups", "GroupInviteToken")
    taken = set()

    for invite_token in GroupInviteToken.objects.filter(code__isnull=True):
        code = groups.models.generate_invite_code()
        while code in taken or GroupInviteToken.objects.filter(code=code).exists():
            code = groups.models.generate_invite_code()

        taken.add(code)
        invite_token.code = code
        invite_token.save(update_fields=["code"])


class Migration(migrations.Migration):

    dependencies = [
        ('groups', '0005_alter_group_created_by'),
    ]

    operations = [
        migrations.AddField(
            model_name='groupinvitetoken',
            name='code',
            field=models.CharField(max_length=8, null=True),
        ),
        migrations.RunPython(fill_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='groupinvitetoken',
            name='code',
            field=models.CharField(
                db_index=True,
                default=groups.models.generate_invite_code,
                max_length=8,
                unique=True,
            ),
        ),
    ]
