import logging
from django.contrib.auth import get_user_model
from django.core.mail import send_mass_mail
from django.conf import settings

logger = logging.getLogger(__name__)

User = get_user_model()


def send_new_movie_email(movie):
    """Notify all opted-in users when a new movie is added."""
    recipient_emails = list(
        User.objects.filter(notify_new_movies=True, is_active=True)
        .exclude(email=None)
        .exclude(email='')
        .values_list('email', flat=True)
    )

    if not recipient_emails:
        return

    subject = f'New on Ikigembe: {movie.title}'
    overview = movie.overview or ''
    snippet = overview[:150] + ('...' if len(overview) > 150 else '')

    message = (
        f'A new movie has just been added to Ikigembe!\n\n'
        f'{movie.title}\n'
        f'{snippet}\n\n'
        f'Price: {movie.price} RWF\n\n'
        f'Log in to watch.\n'
        f'— Ikigembe Team'
    )

    datatuple = tuple(
        (subject, message, settings.DEFAULT_FROM_EMAIL, [email])
        for email in recipient_emails
    )

    try:
        send_mass_mail(datatuple, fail_silently=False)
        logger.info('New movie notification sent to %d users for "%s"', len(recipient_emails), movie.title)
    except Exception:
        logger.exception('Failed to send new movie notification for "%s"', movie.title)
