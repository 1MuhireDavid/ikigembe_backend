# Generated manually — adds phone_number field and makes email nullable
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        # Make email nullable (existing rows keep their email; new rows may omit it)
        migrations.AlterField(
            model_name='user',
            name='email',
            field=models.EmailField(
                blank=True,
                db_index=True,
                max_length=254,
                null=True,
                unique=True,
            ),
        ),
        # Add phone_number field
        migrations.AddField(
            model_name='user',
            name='phone_number',
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=20,
                null=True,
                unique=True,
            ),
        ),
    ]
