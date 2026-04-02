import uuid
import logging
import secrets

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from drf_spectacular.utils import extend_schema, OpenApiResponse, inline_serializer
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers as drf_serializers

from django.utils import timezone
from apps.movies.models import Movie
from apps.payments.models import Payment, WithdrawalRequest
from apps.payments.pawapay import initiate_deposit, detect_correspondent
from apps.payments.emails import send_payment_completed_email, send_withdrawal_status_email
import requests

logger = logging.getLogger(__name__)


class InitiatePaymentView(APIView):
    """Viewer initiates a movie purchase via Mobile Money (PawaPay)."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Payments'],
        summary='Initiate movie purchase',
        description=(
            'Creates a pending payment and sends a Mobile Money prompt to the viewer\'s phone. '
            'Supported networks: MTN (078/079) and Airtel (072/073).'
        ),
        request=inline_serializer(
            name='InitiatePaymentRequest',
            fields={
                'movie_id': drf_serializers.IntegerField(),
                'phone_number': drf_serializers.CharField(help_text='Rwanda phone number (e.g. 0781234567)'),
            }
        ),
        responses={
            202: inline_serializer(
                name='InitiatePaymentResponse',
                fields={
                    'deposit_id': drf_serializers.UUIDField(),
                    'status': drf_serializers.CharField(),
                    'message': drf_serializers.CharField(),
                    'amount': drf_serializers.IntegerField(),
                    'currency': drf_serializers.CharField(),
                }
            ),
            400: OpenApiResponse(description='Invalid input or unrecognized phone prefix'),
            402: OpenApiResponse(description='Movie already purchased'),
            404: OpenApiResponse(description='Movie not found'),
        }
    )
    def post(self, request):
        movie_id = request.data.get('movie_id')
        phone_number = request.data.get('phone_number', '').strip()

        if not movie_id:
            return Response({'error': 'movie_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not phone_number:
            return Response({'error': 'phone_number is required.'}, status=status.HTTP_400_BAD_REQUEST)

        # Validate phone prefix before hitting the DB
        if not detect_correspondent(phone_number):
            return Response(
                {'error': 'Unrecognized phone number. Use an MTN (078/079) or Airtel (072/073) Rwanda number.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            movie = Movie.objects.get(id=movie_id, is_active=True)
        except Movie.DoesNotExist:
            return Response({'error': 'Movie not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Prevent duplicate purchases and double-prompts for the same attempt
        existing = Payment.objects.filter(
            user=request.user, movie=movie, status__in=['Completed', 'Pending']
        ).values_list('status', flat=True).first()
        if existing == 'Completed':
            return Response(
                {'error': 'You have already purchased this movie.'},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )
        if existing == 'Pending':
            return Response(
                {'error': 'A payment for this movie is already in progress. Please approve the MoMo prompt or wait for it to expire.'},
                status=status.HTTP_409_CONFLICT,
            )

        deposit_id = str(uuid.uuid4())

        # Create pending payment record before calling PawaPay
        with transaction.atomic():
            payment = Payment.objects.create(
                user=request.user,
                movie=movie,
                amount=movie.price,
                status='Pending',
                deposit_id=deposit_id,
                phone_number=phone_number,
            )

        # Call PawaPay
        try:
            pawapay_response = initiate_deposit(
                deposit_id=deposit_id,
                amount=movie.price,
                phone_number=phone_number,
                description=f'Ikigembe {movie.title}'[:22],
            )
        except ValueError as e:
            payment.status = 'Failed'
            payment.save(update_fields=['status'])
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except requests.RequestException as e:
            payment.status = 'Failed'
            payment.save(update_fields=['status'])
            logger.error('PawaPay API error for deposit %s: %s', deposit_id, e)
            return Response(
                {'error': 'Payment service error. Please try again.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        pawapay_status = pawapay_response.get('status', '')
        if pawapay_status not in ('ACCEPTED', 'COMPLETED'):
            rejection_reason = pawapay_response.get('rejectionReason', {})
            rejection_code = rejection_reason.get('rejectionCode', pawapay_status)
            payment.status = 'Failed'
            payment.save(update_fields=['status'])
            logger.error('PawaPay deposit rejected for %s: %s', deposit_id, pawapay_response)
            return Response(
                {'error': f'Payment rejected: {rejection_code}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({
            'deposit_id': deposit_id,
            'status': 'Pending',
            'message': 'A Mobile Money prompt has been sent to your phone. Please approve to complete the purchase.',
            'amount': movie.price,
            'currency': 'RWF',
        }, status=status.HTTP_202_ACCEPTED)


class PaymentStatusView(APIView):
    """Check the status of a payment by deposit_id. Only the payment owner can query."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Payments'],
        summary='Check payment status',
        description=(
            'Poll this endpoint after initiating a payment to check if PawaPay has confirmed it. '
            'Returns the current status: Pending, Completed, or Failed.'
        ),
        responses={
            200: inline_serializer(
                name='PaymentStatusResponse',
                fields={
                    'deposit_id': drf_serializers.CharField(),
                    'status': drf_serializers.CharField(),
                    'amount': drf_serializers.IntegerField(),
                    'currency': drf_serializers.CharField(),
                    'movie_id': drf_serializers.IntegerField(allow_null=True),
                    'movie_title': drf_serializers.CharField(allow_null=True),
                    'created_at': drf_serializers.DateTimeField(),
                }
            ),
            403: OpenApiResponse(description='Not your payment'),
            404: OpenApiResponse(description='Payment not found'),
        }
    )
    def get(self, request, deposit_id):
        payment = get_object_or_404(Payment.objects.select_related('movie'), deposit_id=deposit_id)

        if payment.user != request.user:
            return Response({'error': 'Not your payment.'}, status=status.HTTP_403_FORBIDDEN)

        return Response({
            'deposit_id': payment.deposit_id,
            'status': payment.status,
            'amount': payment.amount,
            'currency': 'RWF',
            'movie_id': payment.movie.id if payment.movie else None,
            'movie_title': payment.movie.title if payment.movie else None,
            'created_at': payment.created_at,
        })


class PawapayWebhookView(APIView):
    """
    Single webhook endpoint for all PawaPay callbacks: deposits, payouts, and refunds.
    PawaPay does not send JWT tokens — no authentication required.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        tags=['Payments'],
        summary='PawaPay webhook (internal)',
        description=(
            'Receives callbacks from PawaPay for deposits, payouts, and refunds. '
            'Do not call this directly.'
        ),
        request=inline_serializer(
            name='PawapayWebhookPayload',
            fields={
                'depositId': drf_serializers.CharField(required=False),
                'payoutId': drf_serializers.CharField(required=False),
                'refundId': drf_serializers.CharField(required=False),
                'status': drf_serializers.CharField(),
            }
        ),
        responses={200: OpenApiResponse(description='Acknowledged')}
    )
    def post(self, request):
        auth_header = request.headers.get('Authorization', '')
        expected = f'Bearer {settings.PAWAPAY_API_KEY}'
        if not settings.PAWAPAY_API_KEY or not secrets.compare_digest(auth_header, expected):
            logger.warning('PawaPay webhook: invalid or missing Authorization header')
            return Response(status=status.HTTP_200_OK)

        data = request.data
        pawapay_status = data.get('status', '').upper()

        if data.get('depositId'):
            return self._handle_deposit(data.get('depositId'), pawapay_status)

        if data.get('payoutId'):
            return self._handle_payout(data.get('payoutId'), pawapay_status)

        if data.get('refundId'):
            return self._handle_refund(data.get('refundId'), pawapay_status)

        logger.warning('PawaPay webhook: unrecognized payload — %s', data)
        return Response(status=status.HTTP_200_OK)

    def _handle_deposit(self, deposit_id, pawapay_status):
        """Update Payment status when a deposit is resolved."""
        try:
            payment = Payment.objects.get(deposit_id=deposit_id)
        except Payment.DoesNotExist:
            logger.warning('Webhook: unknown depositId %s', deposit_id)
            return Response(status=status.HTTP_200_OK)

        if payment.status in ('Completed', 'Failed'):
            return Response(status=status.HTTP_200_OK)

        if pawapay_status == 'COMPLETED':
            payment.status = 'Completed'
        elif pawapay_status == 'FAILED':
            payment.status = 'Failed'
        else:
            return Response(status=status.HTTP_200_OK)

        payment.save(update_fields=['status'])
        logger.info('Deposit %s → Payment #%s marked %s', deposit_id, payment.id, payment.status)

        if payment.status == 'Completed':
            send_payment_completed_email(payment)

        return Response(status=status.HTTP_200_OK)

    def _handle_payout(self, payout_id, pawapay_status):
        """Update WithdrawalRequest status when a MoMo payout is resolved."""
        try:
            withdrawal = WithdrawalRequest.objects.get(payout_id=payout_id)
        except WithdrawalRequest.DoesNotExist:
            logger.warning('Webhook: unknown payoutId %s', payout_id)
            return Response(status=status.HTTP_200_OK)

        if withdrawal.status in ('Completed', 'Failed'):
            return Response(status=status.HTTP_200_OK)

        if pawapay_status == 'COMPLETED':
            withdrawal.status = 'Completed'
            withdrawal.processed_at = timezone.now()
            withdrawal.save(update_fields=['status', 'processed_at'])
        elif pawapay_status == 'FAILED':
            withdrawal.status = 'Failed'
            withdrawal.save(update_fields=['status'])
        else:
            return Response(status=status.HTTP_200_OK)

        logger.info('Payout %s → Withdrawal #%s marked %s', payout_id, withdrawal.id, withdrawal.status)
        send_withdrawal_status_email(withdrawal)
        return Response(status=status.HTTP_200_OK)

    def _handle_refund(self, refund_id, pawapay_status):
        """
        Handle refund callbacks.
        Logs for now — will be wired when refund flow is implemented.
        """
        logger.info('Refund callback received: refundId=%s status=%s', refund_id, pawapay_status)
        return Response(status=status.HTTP_200_OK)
