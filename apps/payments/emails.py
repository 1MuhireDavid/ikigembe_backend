import logging
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from apps.users.emails import _base_html, _cta_button, _send, _GOLD, _DARK

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Payment confirmation
# ---------------------------------------------------------------------------

def send_payment_completed_email(payment) -> None:
    """Send a purchase confirmation email to the viewer after MoMo payment is confirmed."""
    user = payment.user
    if not user.email:
        return

    movie_title = payment.movie.title if payment.movie else 'your movie'
    name = user.first_name or 'there'
    amount = f'{payment.amount:,} RWF'

    plain = (
        f'Hi {name},\n\n'
        f'Your payment of {amount} for "{movie_title}" has been confirmed.\n'
        f'You can now stream the movie from your library.\n\n'
        f'Enjoy watching!\n'
        f'— The Ikigembe Team'
    )

    body_html = f"""
        <p style="margin:0 0 4px;color:{_GOLD};font-size:11px;letter-spacing:3px;
                  text-transform:uppercase;font-family:Arial,sans-serif;">
          Purchase Confirmed
        </p>
        <p style="font-size:22px;font-weight:bold;margin:6px 0 20px;color:{_DARK};">
          Enjoy the film, {name}.
        </p>
        <div style="width:48px;height:2px;background:{_GOLD};margin:0 0 24px;"></div>

        <p style="margin:0 0 24px;">
          Your payment has been received. The film is now available in your library —
          ready to stream anytime, anywhere.
        </p>

        <!-- Receipt block -->
        <table width="100%" cellpadding="0" cellspacing="0"
               style="background:{_DARK};border-radius:3px;margin:0 0 28px;
                      overflow:hidden;">
          <tr>
            <td style="padding:20px 24px;border-bottom:1px solid #1e1e1e;">
              <p style="margin:0 0 4px;font-size:11px;color:#888888;letter-spacing:2px;
                        text-transform:uppercase;font-family:Arial,sans-serif;">Film</p>
              <p style="margin:0;font-size:16px;font-weight:bold;color:#ffffff;
                        font-family:Arial,sans-serif;">{movie_title}</p>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 24px;">
              <p style="margin:0 0 4px;font-size:11px;color:#888888;letter-spacing:2px;
                        text-transform:uppercase;font-family:Arial,sans-serif;">Amount Paid</p>
              <p style="margin:0;font-size:20px;font-weight:bold;color:{_GOLD};
                        font-family:Arial,sans-serif;">{amount}</p>
            </td>
          </tr>
        </table>

        {_cta_button('Watch Now', 'https://ikigembe-film.vercel.app/movie-gallery')}

        <p style="margin:0;color:#888888;font-size:12px;font-family:Arial,sans-serif;">
          This film has been added to your library and is available any time.
        </p>
    """

    try:
        _send(
            subject=f'Purchase confirmed — {movie_title}',
            plain=plain,
            html=_base_html('Purchase Confirmed', body_html),
            to=user.email,
        )
        logger.info('Payment confirmation email sent to %s for "%s"', user.email, movie_title)
    except Exception:
        logger.exception('Failed to send payment confirmation email to %s', user.email)


# ---------------------------------------------------------------------------
# Withdrawal status emails (for producers)
# ---------------------------------------------------------------------------

_WITHDRAWAL_STATUS_CONFIG = {
    'Approved': {
        'subject': 'Your withdrawal has been approved',
        'label':   'Approved',
        'accent':  _GOLD,
        'heading': 'Withdrawal Approved',
        'intro':   'Great news — your withdrawal request has been approved by the Ikigembe team.',
        'message': 'We are now processing your payout. Funds will be sent to your registered account shortly.',
        'detail_label': 'Next Step',
        'detail_value': 'Sit tight — your transfer is on its way.',
    },
    'Rejected': {
        'subject': 'Your withdrawal request could not be approved',
        'label':   'Rejected',
        'accent':  '#C0392B',
        'heading': 'Withdrawal Not Approved',
        'intro':   'Unfortunately, your withdrawal request could not be approved at this time.',
        'message': 'Your balance remains intact and available for a future withdrawal request.',
        'detail_label': 'Next Step',
        'detail_value': 'If you believe this is an error, please contact our support team.',
    },
    'Completed': {
        'subject': 'Withdrawal completed — funds sent',
        'label':   'Completed',
        'accent':  '#27AE60',
        'heading': 'Funds Sent',
        'intro':   'Your withdrawal has been completed and funds have been dispatched to your account.',
        'message': 'Bank transfers may take 1–3 business days to reflect. MoMo transfers are typically instant.',
        'detail_label': 'Status',
        'detail_value': 'Transfer complete.',
    },
    'Failed': {
        'subject': 'Withdrawal failed — action required',
        'label':   'Failed',
        'accent':  '#E67E22',
        'heading': 'Withdrawal Failed',
        'intro':   'We were unable to process your withdrawal due to a payout network issue.',
        'message': 'Your balance has been restored. Please try submitting a new withdrawal request.',
        'detail_label': 'Next Step',
        'detail_value': 'Submit a new request or contact support@ikigembe.com for assistance.',
    },
}


def send_withdrawal_status_email(withdrawal) -> None:
    """
    Notify a producer about a status change on their withdrawal request.
    Handles: Approved, Rejected, Completed, Failed.
    """
    producer = withdrawal.producer
    if not producer.email:
        return

    config = _WITHDRAWAL_STATUS_CONFIG.get(withdrawal.status)
    if not config:
        return

    name   = producer.first_name or 'there'
    amount = f'{withdrawal.amount:,} RWF'
    method = withdrawal.payment_method or 'N/A'
    accent = config['accent']

    plain = (
        f'Hi {name},\n\n'
        f'{config["intro"]}\n\n'
        f'{config["message"]}\n\n'
        f'Amount: {amount}\n'
        f'Method: {method}\n\n'
        f'— The Ikigembe Team'
    )

    body_html = f"""
        <p style="margin:0 0 4px;color:{accent};font-size:11px;letter-spacing:3px;
                  text-transform:uppercase;font-family:Arial,sans-serif;">
          Withdrawal · {config['label']}
        </p>
        <p style="font-size:22px;font-weight:bold;margin:6px 0 20px;color:{_DARK};">
          {config['heading']}
        </p>
        <div style="width:48px;height:2px;background:{accent};margin:0 0 24px;"></div>

        <p style="margin:0 0 12px;">Hi {name},</p>
        <p style="margin:0 0 24px;">{config['intro']}</p>
        <p style="margin:0 0 28px;color:#555555;">{config['message']}</p>

        <!-- Details block -->
        <table width="100%" cellpadding="0" cellspacing="0"
               style="background:{_DARK};border-radius:3px;margin:0 0 28px;
                      overflow:hidden;border-left:4px solid {accent};">
          <tr>
            <td style="padding:18px 24px;border-bottom:1px solid #1e1e1e;">
              <p style="margin:0 0 4px;font-size:11px;color:#888888;letter-spacing:2px;
                        text-transform:uppercase;font-family:Arial,sans-serif;">Amount</p>
              <p style="margin:0;font-size:20px;font-weight:bold;color:{_GOLD};
                        font-family:Arial,sans-serif;">{amount}</p>
            </td>
          </tr>
          <tr>
            <td style="padding:18px 24px;border-bottom:1px solid #1e1e1e;">
              <p style="margin:0 0 4px;font-size:11px;color:#888888;letter-spacing:2px;
                        text-transform:uppercase;font-family:Arial,sans-serif;">Payment Method</p>
              <p style="margin:0;font-size:15px;color:#ffffff;
                        font-family:Arial,sans-serif;">{method}</p>
            </td>
          </tr>
          <tr>
            <td style="padding:18px 24px;">
              <p style="margin:0 0 4px;font-size:11px;color:#888888;letter-spacing:2px;
                        text-transform:uppercase;font-family:Arial,sans-serif;">
                {config['detail_label']}
              </p>
              <p style="margin:0;font-size:14px;color:#cccccc;
                        font-family:Arial,sans-serif;">{config['detail_value']}</p>
            </td>
          </tr>
        </table>

        <p style="margin:0;color:#888888;font-size:12px;font-family:Arial,sans-serif;">
          Questions? Contact us at
          <a href="mailto:support@ikigembe.com"
             style="color:{_GOLD};text-decoration:none;">support@ikigembe.com</a>
        </p>
    """

    try:
        _send(
            subject=config['subject'],
            plain=plain,
            html=_base_html(config['heading'], body_html),
            to=producer.email,
        )
        logger.info(
            'Withdrawal status email (%s) sent to %s for withdrawal #%s',
            withdrawal.status, producer.email, withdrawal.id,
        )
    except Exception:
        logger.exception(
            'Failed to send withdrawal status email to %s for withdrawal #%s',
            producer.email, withdrawal.id,
        )
