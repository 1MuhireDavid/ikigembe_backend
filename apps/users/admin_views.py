import uuid
import secrets
import logging

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, serializers as drf_serializers
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import (
    extend_schema,
    inline_serializer,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes
from django.db.models import Sum, Count, Q
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.utils import timezone
from requests import HTTPError as RequestsHTTPError
from requests import RequestException as RequestsRequestException

from apps.users.permissions import IsAdminRole
from apps.users.serializers import AdminCreateProducerSerializer
from apps.movies.models import Movie
from apps.payments.models import Payment, WithdrawalRequest
from apps.payments.serializers import AdminWithdrawalRequestSerializer, get_producer_wallet
from apps.payments.pawapay import initiate_payout
from apps.payments.emails import send_withdrawal_status_email

logger = logging.getLogger(__name__)

User = get_user_model()

_TAG = 'Admin Dashboard'


def _safe_page(request):
    """Return a valid page number from ?page=, defaulting to 1 for any invalid input."""
    try:
        return max(1, int(request.GET.get('page', 1)))
    except (TypeError, ValueError):
        return 1


class AdminBaseView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]


# ─────────────────────────────────────────────
# Dashboard Overview
# ─────────────────────────────────────────────

class AdminDashboardOverviewView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='Platform activity overview',
        description=(
            'Returns platform-wide counters and a full financials breakdown. '
            'Revenue split: 70% producer / 30% Ikigembe commission.'
        ),
        responses={
            200: inline_serializer(
                name='DashboardOverview',
                fields={
                    'total_viewers': drf_serializers.IntegerField(help_text='Total registered viewer accounts'),
                    'total_producers': drf_serializers.IntegerField(help_text='Total registered producer accounts'),
                    'total_movies': drf_serializers.IntegerField(help_text='Total movies in the system'),
                    'total_views': drf_serializers.IntegerField(help_text='Sum of all movie view counts'),
                    'financials': inline_serializer(
                        name='DashboardFinancials',
                        fields={
                            'total_revenue': drf_serializers.IntegerField(help_text='All-time completed payment revenue (RWF)'),
                            'producer_revenue': drf_serializers.IntegerField(help_text='70% share owed to producers (RWF)'),
                            'ikigembe_commission': drf_serializers.IntegerField(help_text='30% platform commission (RWF)'),
                            'revenue_today': drf_serializers.IntegerField(help_text='Revenue from today (RWF)'),
                            'revenue_this_month': drf_serializers.IntegerField(help_text='Revenue from current calendar month (RWF)'),
                            'total_paid_to_producers': drf_serializers.IntegerField(help_text='Sum of Approved + Completed withdrawal requests (RWF)'),
                            'total_profit': drf_serializers.IntegerField(help_text='total_revenue minus total_paid_to_producers (RWF)'),
                        },
                    ),
                },
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
        },
    )
    def get(self, request):
        total_viewers = User.objects.filter(role='Viewer').count()
        total_producers = User.objects.filter(role='Producer').count()
        total_movies = Movie.objects.count()
        total_views = Movie.objects.aggregate(total=Sum('views'))['total'] or 0

        from django.utils import timezone
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = today_start.replace(day=1)

        total_revenue = Payment.objects.filter(status='Completed').aggregate(total=Sum('amount'))['total'] or 0
        producer_revenue = (total_revenue * 70) // 100
        ikigembe_commission = total_revenue - producer_revenue

        revenue_today = Payment.objects.filter(status='Completed', created_at__gte=today_start).aggregate(total=Sum('amount'))['total'] or 0
        revenue_this_month = Payment.objects.filter(status='Completed', created_at__gte=month_start).aggregate(total=Sum('amount'))['total'] or 0

        total_paid_to_producers = WithdrawalRequest.objects.filter(status__in=['Approved', 'Completed']).aggregate(total=Sum('amount'))['total'] or 0
        total_profit = total_revenue - total_paid_to_producers

        return Response({
            'total_viewers': total_viewers,
            'total_producers': total_producers,
            'total_movies': total_movies,
            'total_views': total_views,
            'financials': {
                'total_revenue': total_revenue,
                'producer_revenue': producer_revenue,
                'ikigembe_commission': ikigembe_commission,
                'revenue_today': revenue_today,
                'revenue_this_month': revenue_this_month,
                'total_paid_to_producers': total_paid_to_producers,
                'total_profit': total_profit
            }
        })


# ─────────────────────────────────────────────
# Transaction History
# ─────────────────────────────────────────────

class AdminTransactionHistoryView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='All platform transactions',
        description=(
            'Returns three lists: completed/failed movie payments, '
            'processed withdrawal requests (Approved/Completed/Rejected), '
            'and pending withdrawal requests awaiting admin action.'
        ),
        responses={
            200: inline_serializer(
                name='TransactionHistory',
                fields={
                    'payments': inline_serializer(
                        name='PaymentItem',
                        fields={
                            'id': drf_serializers.IntegerField(),
                            'user': drf_serializers.CharField(help_text='Full name of the paying viewer'),
                            'movie_title': drf_serializers.CharField(),
                            'amount': drf_serializers.IntegerField(help_text='Amount paid in RWF'),
                            'status': drf_serializers.CharField(help_text='Pending | Completed | Failed'),
                            'created_at': drf_serializers.DateTimeField(),
                        },
                        many=True,
                    ),
                    'withdrawals': AdminWithdrawalRequestSerializer(many=True),
                    'pending_withdrawals': AdminWithdrawalRequestSerializer(many=True),
                },
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
        },
    )
    def get(self, request):
        payments = Payment.objects.all().select_related('user', 'movie').order_by('-created_at')
        withdrawals = WithdrawalRequest.objects.exclude(status='Pending').select_related('producer').order_by('-created_at')
        pending_withdrawals = WithdrawalRequest.objects.filter(status='Pending').select_related('producer').order_by('-created_at')

        payments_data = [{
            'id': p.id,
            'user': p.user.full_name,
            'movie_title': p.movie.title if p.movie else 'Unknown',
            'amount': p.amount,
            'status': p.status,
            'created_at': p.created_at,
        } for p in payments]

        return Response({
            'payments': payments_data,
            'withdrawals': AdminWithdrawalRequestSerializer(withdrawals, many=True).data,
            'pending_withdrawals': AdminWithdrawalRequestSerializer(pending_withdrawals, many=True).data,
        })


# ─────────────────────────────────────────────
# Viewers
# ─────────────────────────────────────────────

class AdminViewersListView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='List all viewers',
        description='Returns every viewer account with purchase statistics.',
        responses={
            200: inline_serializer(
                name='ViewerItem',
                fields={
                    'id': drf_serializers.IntegerField(),
                    'name': drf_serializers.CharField(help_text='Full name'),
                    'email': drf_serializers.EmailField(allow_null=True),
                    'phone_number': drf_serializers.CharField(allow_null=True),
                    'movies_watched': drf_serializers.IntegerField(help_text='Number of movies purchased'),
                    'payments_made': drf_serializers.IntegerField(help_text='Total amount spent in RWF'),
                    'is_active': drf_serializers.BooleanField(),
                    'date_joined': drf_serializers.DateTimeField(),
                },
                many=True,
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
        },
    )
    def get(self, request):
        viewers = User.objects.filter(role='Viewer').annotate(
            movies_watched=Count('payments', filter=Q(payments__status='Completed')),
            payments_made=Sum('payments__amount', filter=Q(payments__status='Completed'))
        )
        data = []
        for v in viewers:
            data.append({
                'id': v.id,
                'name': v.full_name,
                'email': v.email,
                'phone_number': v.phone_number,
                'movies_watched': v.movies_watched,
                'payments_made': v.payments_made or 0,
                'is_active': v.is_active,
                'date_joined': v.date_joined
            })
        return Response(data)


class AdminViewerPaymentsView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary="A specific viewer's payment history",
        description='Returns all movie purchases made by the given viewer, newest first.',
        responses={
            200: inline_serializer(
                name='ViewerPaymentItem',
                fields={
                    'id': drf_serializers.IntegerField(),
                    'movie_title': drf_serializers.CharField(),
                    'amount': drf_serializers.IntegerField(help_text='Amount paid in RWF'),
                    'status': drf_serializers.CharField(help_text='Pending | Completed | Failed'),
                    'created_at': drf_serializers.DateTimeField(),
                },
                many=True,
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
            404: OpenApiResponse(description='Viewer not found'),
        },
    )
    def get(self, request, user_id):
        user = get_object_or_404(User, id=user_id, role='Viewer')
        payments = Payment.objects.filter(user=user).select_related('movie').order_by('-created_at')
        data = []
        for p in payments:
            data.append({
                'id': p.id,
                'movie_title': p.movie.title if p.movie else 'Unknown',
                'amount': p.amount,
                'status': p.status,
                'created_at': p.created_at
            })
        return Response(data)


# ─────────────────────────────────────────────
# User Management (Suspend / Delete)
# ─────────────────────────────────────────────

class AdminUserSuspendView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='Toggle user suspension',
        description=(
            'Toggles `is_active` on a Viewer or Producer account. '
            'Suspended users cannot log in. Admin accounts cannot be suspended.'
        ),
        request=None,
        responses={
            200: inline_serializer(
                name='UserSuspendResponse',
                fields={
                    'message': drf_serializers.CharField(help_text='e.g. "User suspended successfully"'),
                    'is_active': drf_serializers.BooleanField(help_text='New active state after the toggle'),
                },
            ),
            400: OpenApiResponse(description='Cannot suspend an Admin account'),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
            404: OpenApiResponse(description='User not found'),
        },
    )
    def post(self, request, user_id):
        user = get_object_or_404(User, id=user_id)
        if user.role == 'Admin':
            return Response({'error': 'Cannot suspend another Admin'}, status=status.HTTP_400_BAD_REQUEST)

        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])
        state = "activated" if user.is_active else "suspended"
        return Response({'message': f'User {state} successfully', 'is_active': user.is_active})


class AdminUserDeleteView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='Delete a user account',
        description='Permanently deletes a Viewer or Producer account. Admin accounts cannot be deleted.',
        responses={
            204: OpenApiResponse(description='User deleted successfully'),
            400: OpenApiResponse(description='Cannot delete an Admin account'),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
            404: OpenApiResponse(description='User not found'),
        },
    )
    def delete(self, request, user_id):
        user = get_object_or_404(User, id=user_id)
        if user.role == 'Admin':
            return Response({'error': 'Cannot delete an Admin'}, status=status.HTTP_400_BAD_REQUEST)
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────────
# Producers
# ─────────────────────────────────────────────

class AdminProducersListView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='List all producers with earnings stats',
        description='Returns every producer account enriched with wallet and movie upload statistics.',
        responses={
            200: inline_serializer(
                name='ProducerItem',
                fields={
                    'id': drf_serializers.IntegerField(),
                    'name': drf_serializers.CharField(help_text='Full name'),
                    'email': drf_serializers.EmailField(allow_null=True),
                    'phone_number': drf_serializers.CharField(allow_null=True),
                    'movies_uploaded': drf_serializers.IntegerField(),
                    'total_earnings': drf_serializers.IntegerField(help_text='70% share of revenue from their movies (RWF)'),
                    'balance': drf_serializers.IntegerField(help_text='Available balance for withdrawal (RWF)'),
                    'pending_withdrawals': drf_serializers.IntegerField(help_text='Amount locked in pending withdrawal requests (RWF)'),
                    'total_withdrawn': drf_serializers.IntegerField(help_text='Total amount paid out (RWF)'),
                    'is_active': drf_serializers.BooleanField(),
                    'date_joined': drf_serializers.DateTimeField(),
                },
                many=True,
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
        },
    )
    def get(self, request):
        producers = list(User.objects.filter(role='Producer').annotate(
            movies_uploaded_count=Count('uploaded_movies', distinct=True),
        ))
        producer_ids = [p.id for p in producers]

        # Batch all financial aggregations in 3 queries (instead of 3–4 per producer).
        revenue_map = {
            row['movie__producer_profile_id']: row['total']
            for row in Payment.objects.filter(
                movie__producer_profile_id__in=producer_ids,
                status='Completed',
            ).values('movie__producer_profile_id').annotate(total=Sum('amount'))
        }

        locked_map = {
            row['producer_id']: row['total']
            for row in WithdrawalRequest.objects.filter(
                producer_id__in=producer_ids,
                status__in=['Pending', 'Approved', 'Processing', 'Completed'],
            ).values('producer_id').annotate(total=Sum('amount'))
        }

        pending_map = {
            row['producer_id']: row['total']
            for row in WithdrawalRequest.objects.filter(
                producer_id__in=producer_ids,
                status='Pending',
            ).values('producer_id').annotate(total=Sum('amount'))
        }

        withdrawn_map = {
            row['producer_id']: row['total']
            for row in WithdrawalRequest.objects.filter(
                producer_id__in=producer_ids,
                status='Completed',
            ).values('producer_id').annotate(total=Sum('amount'))
        }

        data = []
        for p in producers:
            raw_revenue = revenue_map.get(p.id) or 0
            total_earnings = (raw_revenue * 70) // 100
            locked = locked_map.get(p.id) or 0
            data.append({
                'id': p.id,
                'name': p.full_name,
                'email': p.email,
                'phone_number': p.phone_number,
                'movies_uploaded': p.movies_uploaded_count,
                'total_earnings': total_earnings,
                'balance': total_earnings - locked,
                'pending_withdrawals': pending_map.get(p.id) or 0,
                'total_withdrawn': withdrawn_map.get(p.id) or 0,
                'is_active': p.is_active,
                'date_joined': p.date_joined,
            })
        return Response(data)


class AdminProducerApproveView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='Approve (activate) a producer account',
        description='Sets `is_active=True` on a producer account, granting them access to the platform.',
        request=None,
        responses={
            200: inline_serializer(
                name='ProducerApproveResponse',
                fields={'message': drf_serializers.CharField()},
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
            404: OpenApiResponse(description='Producer not found'),
        },
    )
    def post(self, request, user_id):
        producer = get_object_or_404(User, id=user_id, role='Producer')

        if producer.is_active:
            return Response({'message': 'Producer is already approved (active)'}, status=status.HTTP_200_OK)

        producer.is_active = True
        producer.save(update_fields=['is_active'])
        return Response({'message': 'Producer approved successfully'})


class AdminProducerSuspendView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='Suspend a producer account',
        description='Sets `is_active=False` on a producer. The producer cannot log in while suspended.',
        request=None,
        responses={
            200: inline_serializer(
                name='ProducerSuspendResponse',
                fields={'message': drf_serializers.CharField()},
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
            404: OpenApiResponse(description='Producer not found'),
        },
    )
    def post(self, request, user_id):
        producer = get_object_or_404(User, id=user_id, role='Producer')
        producer.is_active = False
        producer.save(update_fields=['is_active'])
        return Response({'message': 'Producer suspended successfully'})


class AdminCreateProducerView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='Create a new producer account',
        description=(
            'Creates a producer account with an auto-generated temporary password. '
            'The password is returned once — it is not stored in plain text and cannot be retrieved again. '
            'At least one of `email` or `phone_number` is required.'
        ),
        request=inline_serializer(
            name='CreateProducerRequest',
            fields={
                'email': drf_serializers.EmailField(required=False, allow_null=True, help_text='Optional if phone_number is provided'),
                'phone_number': drf_serializers.CharField(required=False, allow_null=True, help_text='Optional if email is provided'),
                'first_name': drf_serializers.CharField(required=False, allow_blank=True, default=''),
                'last_name': drf_serializers.CharField(required=False, allow_blank=True, default=''),
            },
        ),
        responses={
            201: inline_serializer(
                name='CreateProducerResponse',
                fields={
                    'id': drf_serializers.IntegerField(),
                    'email': drf_serializers.EmailField(allow_null=True),
                    'phone_number': drf_serializers.CharField(allow_null=True),
                    'full_name': drf_serializers.CharField(),
                    'role': drf_serializers.CharField(help_text='Always "Producer"'),
                    'generated_password': drf_serializers.CharField(
                        help_text='Temporary password — share with the producer and ask them to change it immediately'
                    ),
                },
            ),
            400: OpenApiResponse(description='Validation error (missing identifier or duplicate email/phone)'),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
        },
    )
    def post(self, request):
        email = request.data.get('email') or None
        first_name = request.data.get('first_name', '')
        last_name = request.data.get('last_name', '')
        phone_number = request.data.get('phone_number') or None

        if not email and not phone_number:
            return Response({'error': 'Email or phone number is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if email and User.objects.filter(email=email).exists():
            return Response({'error': 'A user with this email already exists.'}, status=status.HTTP_400_BAD_REQUEST)
        if phone_number and User.objects.filter(phone_number=phone_number).exists():
            return Response({'error': 'A user with this phone number already exists.'}, status=status.HTTP_400_BAD_REQUEST)

        password = secrets.token_urlsafe(10)
        user = User.objects.create_user(
            email=email,
            phone_number=phone_number,
            first_name=first_name,
            last_name=last_name,
            password=password,
            role='Producer',
            is_active=True,
        )
        return Response({
            'id': user.id,
            'email': user.email,
            'phone_number': user.phone_number,
            'full_name': user.full_name,
            'role': user.role,
            'generated_password': password,
        }, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────
# Withdrawal Request Management
# ─────────────────────────────────────────────

class AdminWithdrawalsListView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='List producer withdrawal requests',
        description=(
            'Returns paginated withdrawal requests. '
            'Filter by `?status=Pending|Approved|Completed|Rejected`. '
            'Without a filter, all statuses are returned.'
        ),
        parameters=[
            OpenApiParameter(
                name='status',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=['Pending', 'Approved', 'Completed', 'Rejected'],
                description='Filter by withdrawal status',
            ),
            OpenApiParameter(
                name='page',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                default=1,
                description='Page number (20 results per page)',
            ),
        ],
        responses={
            200: inline_serializer(
                name='WithdrawalListResponse',
                fields={
                    'page': drf_serializers.IntegerField(),
                    'total_results': drf_serializers.IntegerField(),
                    'total_pages': drf_serializers.IntegerField(),
                    'results': AdminWithdrawalRequestSerializer(many=True),
                },
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
        },
    )
    def get(self, request):
        qs = WithdrawalRequest.objects.select_related('producer').order_by('-created_at')
        status_filter = request.GET.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        page = _safe_page(request)
        page_size = 20
        start = (page - 1) * page_size
        total = qs.count()

        return Response({
            'page': page,
            'results': AdminWithdrawalRequestSerializer(qs[start:start + page_size], many=True).data,
            'total_results': total,
            'total_pages': (total + page_size - 1) // page_size,
        })


class AdminWithdrawalApproveView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='Approve a withdrawal request',
        description='Moves the withdrawal from **Pending → Approved**. Only Pending requests can be approved.',
        request=None,
        responses={
            200: inline_serializer(
                name='WithdrawalActionResponse',
                fields={
                    'message': drf_serializers.CharField(),
                    'id': drf_serializers.IntegerField(),
                    'status': drf_serializers.CharField(help_text='New status after the action'),
                },
            ),
            400: OpenApiResponse(description='Withdrawal is not in Pending state'),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
            404: OpenApiResponse(description='Withdrawal not found'),
        },
    )
    def post(self, request, withdrawal_id):
        withdrawal = get_object_or_404(WithdrawalRequest, id=withdrawal_id)

        if withdrawal.status != 'Pending':
            return Response(
                {'error': f"Cannot approve a '{withdrawal.status}' withdrawal. Only Pending requests can be approved."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        withdrawal.status = 'Approved'
        withdrawal.processed_at = timezone.now()
        withdrawal.save(update_fields=['status', 'processed_at'])
        send_withdrawal_status_email(withdrawal)

        return Response({
            'message': 'Withdrawal approved successfully.',
            'id': withdrawal.id,
            'status': withdrawal.status,
            'processed_at': withdrawal.processed_at,
        })


class AdminWithdrawalCompleteView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='Complete a withdrawal request',
        description=(
            'For **MoMo** withdrawals: initiates a PawaPay payout to the producer\'s phone. '
            'Status moves to **Processing** and will be updated to Completed or Failed via webhook. '
            'For **Bank** withdrawals: marks directly as **Completed** (manual transfer assumed). '
            'Only Approved requests can be completed. Completed records are immutable.'
        ),
        request=None,
        responses={
            200: inline_serializer(
                name='WithdrawalCompleteResponse',
                fields={
                    'message': drf_serializers.CharField(),
                    'id': drf_serializers.IntegerField(),
                    'status': drf_serializers.CharField(help_text='New status after the action'),
                },
            ),
            400: OpenApiResponse(description='Withdrawal is not in Approved state, or is already Completed'),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
            404: OpenApiResponse(description='Withdrawal not found'),
            502: OpenApiResponse(description='PawaPay payout API error'),
        },
    )
    def post(self, request, withdrawal_id):
        withdrawal = get_object_or_404(WithdrawalRequest, id=withdrawal_id)

        if withdrawal.status == 'Completed':
            return Response(
                {'error': 'This withdrawal is already completed and cannot be modified.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if withdrawal.status != 'Approved':
            return Response(
                {'error': f"Cannot complete a '{withdrawal.status}' withdrawal. Only Approved requests can be completed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Bank withdrawals: mark complete immediately (manual transfer)
        if withdrawal.payment_method == 'Bank':
            withdrawal.status = 'Completed'
            withdrawal.processed_at = timezone.now()
            withdrawal.save(update_fields=['status', 'processed_at'])
            send_withdrawal_status_email(withdrawal)
            return Response({
                'message': 'Withdrawal marked as completed.',
                'id': withdrawal.id,
                'status': withdrawal.status,
            })

        # MoMo withdrawals: send payout via PawaPay
        if not withdrawal.momo_number:
            return Response(
                {'error': 'No MoMo number on record for this withdrawal.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payout_id = str(uuid.uuid4())
        try:
            pawapay_response = initiate_payout(
                payout_id=payout_id,
                amount=withdrawal.amount,
                phone_number=withdrawal.momo_number,
                description='Ikigembe Earnings',
            )
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except RequestsHTTPError as e:
            withdrawal.payout_id = payout_id
            withdrawal.status = 'Failed'
            withdrawal.processed_at = timezone.now()
            withdrawal.save(update_fields=['payout_id', 'status', 'processed_at'])
            send_withdrawal_status_email(withdrawal)
            logger.error('PawaPay payout error for withdrawal %s: %s', withdrawal_id, e)
            return Response(
                {'error': 'Payout service error. Please try again.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except RequestsRequestException as e:
            withdrawal.payout_id = payout_id
            withdrawal.status = 'Failed'
            withdrawal.processed_at = timezone.now()
            withdrawal.save(update_fields=['payout_id', 'status', 'processed_at'])
            send_withdrawal_status_email(withdrawal)
            logger.error('PawaPay payout connection error for withdrawal %s: %s', withdrawal_id, e)
            return Response(
                {'error': 'Payout service error. Please try again.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        pawapay_status = pawapay_response.get('status', '')
        if pawapay_status not in ('ACCEPTED', 'COMPLETED'):
            withdrawal.status = 'Failed'
            withdrawal.processed_at = timezone.now()
            withdrawal.save(update_fields=['status', 'processed_at'])
            send_withdrawal_status_email(withdrawal)
            return Response(
                {'error': f'Payout rejected by provider: {pawapay_status}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        withdrawal.payout_id = payout_id
        withdrawal.status = 'Processing'
        withdrawal.processed_at = timezone.now()
        withdrawal.save(update_fields=['payout_id', 'status', 'processed_at'])

        return Response({
            'message': 'MoMo payout initiated. Status will update to Completed once confirmed by PawaPay.',
            'id': withdrawal.id,
            'status': withdrawal.status,
        })


class AdminWithdrawalRejectView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='Reject a withdrawal request',
        description=(
            'Moves the withdrawal to **Rejected** from either Pending or Approved state. '
            'The rejected amount is automatically freed back into the producer\'s wallet balance.'
        ),
        request=None,
        responses={
            200: inline_serializer(
                name='WithdrawalRejectResponse',
                fields={
                    'message': drf_serializers.CharField(),
                    'id': drf_serializers.IntegerField(),
                    'status': drf_serializers.CharField(help_text='New status after the action'),
                },
            ),
            400: OpenApiResponse(description='Withdrawal cannot be rejected (already Completed or Rejected)'),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
            404: OpenApiResponse(description='Withdrawal not found'),
        },
    )
    def post(self, request, withdrawal_id):
        withdrawal = get_object_or_404(WithdrawalRequest, id=withdrawal_id)

        if withdrawal.status not in ('Pending', 'Approved'):
            return Response(
                {'error': f"Cannot reject a '{withdrawal.status}' withdrawal."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        withdrawal.status = 'Rejected'
        withdrawal.processed_at = timezone.now()
        withdrawal.save(update_fields=['status', 'processed_at'])
        send_withdrawal_status_email(withdrawal)

        return Response({
            'message': 'Withdrawal rejected.',
            'id': withdrawal.id,
            'status': withdrawal.status,
        })
