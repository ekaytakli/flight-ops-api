# Django 5.2.19 ile 2026-11-16 10:30 tarihinde oluşturuldu.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('incidents', '0002_create_role_groups'),
    ]

    operations = [
        migrations.AddField(
            model_name='incident',
            name='priority',
            field=models.CharField(choices=[('LOW', 'Low'), ('NORMAL', 'Normal'), ('HIGH', 'High'), ('CRITICAL', 'Critical')], db_index=True, default='NORMAL', max_length=8),
        ),
        migrations.AlterField(
            model_name='incidentevent',
            name='event_type',
            field=models.CharField(choices=[('CREATED', 'Created'), ('ASSIGNED', 'Assigned'), ('STARTED', 'Started'), ('RESOLVED', 'Resolved'), ('PRIORITY_CHANGED', 'Priority changed')], max_length=16),
        ),
    ]
