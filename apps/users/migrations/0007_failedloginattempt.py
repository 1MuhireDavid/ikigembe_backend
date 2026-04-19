from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0006_user_address_user_copyright_code'),
    ]

    operations = [
        migrations.CreateModel(
            name='FailedLoginAttempt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ip_address', models.GenericIPAddressField(db_index=True)),
                ('identifier', models.CharField(db_index=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='failedloginattempt',
            index=models.Index(fields=['ip_address', 'identifier', 'created_at'], name='users_faile_ip_addr_idx'),
        ),
    ]
