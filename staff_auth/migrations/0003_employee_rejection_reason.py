from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('staff_auth', '0002_role_enum_and_approval_audit'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='rejection_reason',
            field=models.TextField(blank=True, help_text='Reason for rejecting the employee application.', null=True),
        ),
    ]
