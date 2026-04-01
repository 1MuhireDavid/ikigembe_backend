import logging
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)


def send_payment_completed_email(payment):
    """Send a purchase confirmation email to the viewer after MoMo payment is confirmed."""
    user = payment.user
    if not user.email:
        return

    movie_title = payment.movie.title if payment.movie else 'your movie'
    name = user.first_name or 'there'

    try:
        send_mail(
            subject=f'Purchase confirmed — {movie_title}',
            message=(
                f'Hi {name},\n\n'
                f'Your payment of {payment.amount} RWF for "{movie_title}" has been confirmed.\n'
                f'You can now stream the movie from your library.\n\n'
                f'Enjoy watching!\n'
                f'— Ikigembe Team'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception('Failed to send payment confirmation email to %s', user.email)
