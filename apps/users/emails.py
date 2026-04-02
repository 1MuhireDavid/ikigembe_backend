import logging
from django.core.mail import EmailMultiAlternatives
from django.conf import settings

logger = logging.getLogger(__name__)

_LOGO_URL = 'https://ikigembe-film.vercel.app/assets/ikigembe.log.png'
_GOLD     = '#C9A84C'
_DARK     = '#0A0A0A'

# ---------------------------------------------------------------------------
# Shared HTML shell
# ---------------------------------------------------------------------------

def _base_html(title: str, body_html: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title}</title>
</head>
<body style="margin:0;padding:0;background:#1a1a1a;font-family:Georgia,'Times New Roman',serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a1a;padding:36px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0"
               style="max-width:600px;width:100%;border-radius:4px;overflow:hidden;
                      box-shadow:0 8px 40px rgba(0,0,0,0.6);">

          <!-- Header -->
          <tr>
            <td align="center"
                style="background:{_DARK};padding:32px 40px 24px;
                       border-bottom:3px solid {_GOLD};">
              <img src="{_LOGO_URL}" alt="Ikigembe"
                   style="height:52px;display:block;margin:0 auto 14px;" />
              <p style="margin:0;color:{_GOLD};font-size:11px;letter-spacing:3px;
                        text-transform:uppercase;font-family:Arial,sans-serif;">
                Rwanda's Premier Film Platform
              </p>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="background:#fdfcf8;padding:40px 44px;color:#1a1a1a;
                       font-size:15px;line-height:1.8;">
              {body_html}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background:{_DARK};padding:24px 40px;
                       border-top:1px solid #2a2a2a;">
              <p style="margin:0;font-size:11px;color:#666666;text-align:center;
                        font-family:Arial,sans-serif;letter-spacing:0.5px;">
                &copy; 2025 Ikigembe Film Arts. All rights reserved.<br>
                You received this email because you have an account on Ikigembe.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _cta_button(text: str, url: str) -> str:
    """Gold CTA button for use inside body_html."""
    return (
        f'<p style="text-align:center;margin:28px 0;">'
        f'<a href="{url}"'
        f'   style="display:inline-block;background:{_GOLD};color:{_DARK};'
        f'          text-decoration:none;padding:14px 36px;border-radius:3px;'
        f'          font-size:14px;font-weight:bold;letter-spacing:1px;'
        f'          font-family:Arial,sans-serif;text-transform:uppercase;">'
        f'{text}'
        f'</a>'
        f'</p>'
    )


def _send(subject: str, plain: str, html: str, to: str) -> None:
    msg = EmailMultiAlternatives(
        subject=subject,
        body=plain,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to],
    )
    msg.attach_alternative(html, 'text/html')
    msg.send(fail_silently=False)


# ---------------------------------------------------------------------------
# Welcome email
# ---------------------------------------------------------------------------

def send_welcome_email(user) -> None:
    """Send a welcome email to a newly registered user."""
    if not user.email:
        return

    name = user.first_name or 'there'

    plain = (
        f'Hi {name},\n\n'
        f'Welcome to Ikigembe! Your account is ready.\n\n'
        f'Discover and stream Rwandan-produced movies on your favourite device.\n\n'
        f'Enjoy watching!\n'
        f'— The Ikigembe Team'
    )

    body_html = f"""
        <p style="font-size:22px;font-weight:bold;margin:0 0 6px;color:{_DARK};">
          Welcome, {name}.
        </p>
        <p style="margin:0 0 4px;color:{_GOLD};font-size:12px;letter-spacing:2px;
                  text-transform:uppercase;font-family:Arial,sans-serif;">
          Your journey begins here
        </p>
        <div style="width:48px;height:2px;background:{_GOLD};margin:16px 0 24px;"></div>

        <p style="margin:0 0 16px;">
          Your account is all set. Step into a curated world of Rwandan-produced
          films — drama, comedy, action, documentary and beyond.
        </p>
        <p style="margin:0 0 28px;">
          Whenever a new title drops, we'll make sure you're the first to know.
        </p>

        {_cta_button('Browse Films', 'https://ikigembe-film.vercel.app/movie-gallery')}

        <p style="margin:24px 0 0;color:#777777;font-size:13px;
                  font-family:Arial,sans-serif;">
          Questions? Reply to this email and we'll be happy to help.
        </p>
    """

    try:
        _send(
            subject='Welcome to Ikigembe — Your account is ready',
            plain=plain,
            html=_base_html('Welcome to Ikigembe', body_html),
            to=user.email,
        )
        logger.info('Welcome email sent to %s', user.email)
    except Exception:
        logger.exception('Failed to send welcome email to %s', user.email)
