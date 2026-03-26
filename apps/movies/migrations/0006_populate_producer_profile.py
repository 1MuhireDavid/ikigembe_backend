# Generated manually
from django.db import migrations
from django.conf import settings
import uuid

def populate_producer_profile(apps, schema_editor):
    Movie = apps.get_model('movies', 'Movie')
    User = apps.get_model('users', 'User')

    for movie in Movie.objects.exclude(producer='').exclude(producer__isnull=True):
        if not movie.producer_profile:
            names = movie.producer.strip().split(" ", 1)
            first_name = names[0][:150]
            last_name = names[1][:150] if len(names) > 1 else ""

            producer_user = User.objects.filter(
                role='Producer',
                first_name__iexact=first_name,
                last_name__iexact=last_name
            ).first()

            if not producer_user:
                producer_user = User.objects.create(
                    email=f"legacy_producer_{uuid.uuid4().hex[:8]}@example.com",
                    first_name=first_name,
                    last_name=last_name,
                    role='Producer',
                    is_active=False,
                )
                producer_user.password = "!"
                producer_user.save()

            movie.producer_profile = producer_user
            movie.save(update_fields=['producer_profile'])

def reverse_populate(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0005_movie_producer_profile'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(populate_producer_profile, reverse_populate),
    ]
