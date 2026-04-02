import logging
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from apps.users.emails import _base_html, _cta_button, _GOLD, _DARK

logger = logging.getLogger(__name__)

User = get_user_model()


def send_new_movie_email(movie) -> None:
    """Notify all opted-in users when a new movie is added."""
    recipients = list(
        User.objects.filter(notify_new_movies=True, is_active=True)
        .exclude(email=None)
        .exclude(email='')
        .values_list('email', flat=True)
    )

    if not recipients:
        return

    overview = movie.overview or ''
    snippet = overview[:180] + ('...' if len(overview) > 180 else '')
    price_line = f'{movie.price:,} RWF' if movie.price else 'Free'
    subject = f'Now Showing: {movie.title}'

    plain = (
        f'A new movie has just been added to Ikigembe!\n\n'
        f'{movie.title}\n'
        f'{snippet}\n\n'
        f'Price: {price_line}\n\n'
        f'Log in to watch.\n'
        f'— The Ikigembe Team'
    )

    snippet_block = (
        f'<p style="margin:0 0 24px;color:#444444;font-style:italic;'
        f'font-size:14px;line-height:1.8;border-left:3px solid {_GOLD};'
        f'padding-left:16px;">{snippet}</p>'
        if snippet else ''
    )

    body_html = f"""
        <p style="margin:0 0 4px;color:{_GOLD};font-size:11px;letter-spacing:3px;
                  text-transform:uppercase;font-family:Arial,sans-serif;">
          New Release
        </p>
        <p style="font-size:24px;font-weight:bold;margin:6px 0 20px;color:{_DARK};">
          {movie.title}
        </p>
        <div style="width:48px;height:2px;background:{_GOLD};margin:0 0 24px;"></div>

        {snippet_block}

        <table cellpadding="0" cellspacing="0"
               style="background:#0A0A0A;border-radius:3px;padding:16px 24px;
                      margin:0 0 28px;">
          <tr>
            <td>
              <p style="margin:0 0 4px;font-size:11px;color:#888888;letter-spacing:2px;
                        text-transform:uppercase;font-family:Arial,sans-serif;">
                Admission
              </p>
              <p style="margin:0;font-size:20px;font-weight:bold;color:{_GOLD};
                        font-family:Arial,sans-serif;">
                {price_line}
              </p>
            </td>
          </tr>
        </table>

        {_cta_button('Watch Now', 'https://ikigembe-film.vercel.app/movie-gallery')}

        <p style="font-size:11px;color:#aaaaaa;margin:0;font-family:Arial,sans-serif;">
          You're receiving this because you opted in to new release alerts.&nbsp;
          <a href="https://ikigembe-film.vercel.app/settings/notifications"
             style="color:#aaaaaa;">Manage preferences</a>
        </p>
    """

    html = _base_html(subject, body_html)
    sent = 0
    failed = 0

    for email in recipients:
        try:
            msg = EmailMultiAlternatives(
                subject=subject,
                body=plain,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[email],
            )
            msg.attach_alternative(html, 'text/html')
            msg.send(fail_silently=False)
            sent += 1
        except Exception:
            failed += 1
            logger.exception('Failed to send new-movie email to %s for "%s"', email, movie.title)

    logger.info(
        'New movie notification for "%s": %d sent, %d failed',
        movie.title, sent, failed,
    )


def send_new_trailer_email(movie) -> None:
    """Notify all opted-in users when a trailer is available for a movie."""
    recipients = list(
        User.objects.filter(notify_new_trailers=True, is_active=True)
        .exclude(email=None)
        .exclude(email='')
        .values_list('email', flat=True)
    )

    if not recipients:
        return

    subject = f'Trailer Available: {movie.title}'

    plain = (
        f'A new trailer is now available on Ikigembe!\n\n'
        f'{movie.title}\n\n'
        f'Watch the free trailer now.\n'
        f'— The Ikigembe Team'
    )

    body_html = f"""
        <p style="margin:0 0 4px;color:{_GOLD};font-size:11px;letter-spacing:3px;
                  text-transform:uppercase;font-family:Arial,sans-serif;">
          New Trailer
        </p>
        <p style="font-size:24px;font-weight:bold;margin:6px 0 20px;color:{_DARK};">
          {movie.title}
        </p>
        <div style="width:48px;height:2px;background:{_GOLD};margin:0 0 24px;"></div>

        <p style="margin:0 0 28px;color:#444444;font-family:Arial,sans-serif;font-size:14px;line-height:1.8;">
          A new trailer has just dropped. Watch it free — no purchase needed.
        </p>

        {_cta_button('Watch Trailer', 'https://ikigembe-film.vercel.app/movie-gallery')}

        <p style="font-size:11px;color:#aaaaaa;margin:0;font-family:Arial,sans-serif;">
          You're receiving this because you opted in to trailer alerts.&nbsp;
          <a href="https://ikigembe-film.vercel.app/settings/notifications"
             style="color:#aaaaaa;">Manage preferences</a>
        </p>
    """

    html = _base_html(subject, body_html)
    sent = 0
    failed = 0

    for email in recipients:
        try:
            msg = EmailMultiAlternatives(
                subject=subject,
                body=plain,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[email],
            )
            msg.attach_alternative(html, 'text/html')
            msg.send(fail_silently=False)
            sent += 1
        except Exception:
            failed += 1
            logger.exception('Failed to send trailer email to %s for "%s"', email, movie.title)

    logger.info(
        'Trailer notification for "%s": %d sent, %d failed',
        movie.title, sent, failed,
    )
