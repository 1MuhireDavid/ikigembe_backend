import uuid
import secrets
import logging

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, serializers as drf_serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from drf_spectacular.utils import (
    extend_schema,
    inline_serializer,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes
from django.db import IntegrityError, transaction
from django.db.models import Sum, Count, Q, Max, Min
from django.db.models.functions import Coalesce, TruncDay, TruncMonth, TruncWeek, TruncYear
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.utils import timezone
from requests import HTTPError as RequestsHTTPError
from requests import RequestException as RequestsRequestException

from apps.users.permissions import IsAdminRole
from apps.users.serializers import AdminCreateProducerSerializer
from apps.movies.models import Movie, Subtitle
from apps.movies.serializers import SubtitleSerializer, SubtitleUploadSerializer, SubtitleUpdateSerializer
from apps.payments.models import Payment, WithdrawalRequest
from apps.payments.serializers import AdminWithdrawalRequestSerializer, get_producer_wallet, producer_split
from apps.payments.pawapay import initiate_payout, detect_correspondent
from apps.payments.emails import send_withdrawal_status_email, send_payment_completed_email

logger = logging.getLogger(__name__)

User = get_user_model()


def _log_admin_action(request, action, detail=None, target_user=None, target_withdrawal=None):
    """Persist an audit trail entry for every sensitive admin action."""
    from apps.users.models import AdminAuditLog
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    ip = x_forwarded.split(',')[0].strip() if x_forwarded else request.META.get('REMOTE_ADDR')
    AdminAuditLog.objects.create(
        admin=request.user,
        action=action,
        target_user=target_user,
        target_withdrawal=target_withdrawal,
        detail=detail or {},
        ip_address=ip,
    )
    logger.info('Admin %s performed %s | detail=%s', request.user.email, action, detail)

_TAG = 'Admin Dashboard'
_REPORTS_TAG = 'Admin Reports'


def _safe_page(request):
    """Return a valid page number from ?page=, defaulting to 1 for any invalid input."""
    try:
        return max(1, int(request.GET.get('page', 1)))
    except (TypeError, ValueError):
        return 1


def _parse_date_range(request, default_days):
    """
    Parse optional ?start_date= and ?end_date= (YYYY-MM-DD) from the request.

    - until defaults to now(); since defaults to until - default_days.
    - If default_days is None, since defaults to 2000-01-01 (all available data).
    - end_date is inclusive: it extends to 23:59:59.999999 of that day.
    - since is anchored to until (not now) so historical end_date-only queries
      never produce an empty window due to since > until.

    Returns (since, until) as timezone-aware datetimes.
    """
    from datetime import datetime, timedelta
    since = until = None
    start_raw = request.GET.get('start_date')
    end_raw = request.GET.get('end_date')
    try:
        since = timezone.make_aware(datetime.strptime(start_raw, '%Y-%m-%d')) if start_raw else None
    except ValueError:
        pass
    try:
        until = timezone.make_aware(
            datetime.strptime(end_raw, '%Y-%m-%d').replace(
                hour=23, minute=59, second=59, microsecond=999999
            )
        ) if end_raw else None
    except ValueError:
        pass
    if until is None:
        until = timezone.now()
    if since is None:
        since = (
            timezone.make_aware(datetime(2000, 1, 1))
            if default_days is None
            else until - timedelta(days=default_days)
        )
    return since, until


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
        summary='List all viewers (payment data only)',
        description=(
            'Returns every viewer account with payment statistics. '
            'Use GET /api/admin/dashboard/viewers/<id>/ for full contact details.'
        ),
        responses={
            200: inline_serializer(
                name='ViewerItem',
                fields={
                    'id': drf_serializers.IntegerField(),
                    'name': drf_serializers.CharField(help_text='Full name'),
                    'payment_count': drf_serializers.IntegerField(help_text='Number of completed purchases'),
                    'total_paid_rwf': drf_serializers.IntegerField(help_text='Total amount spent in RWF'),
                    'last_payment_date': drf_serializers.DateTimeField(allow_null=True, help_text='Date of most recent payment'),
                    'is_active': drf_serializers.BooleanField(),
                },
                many=True,
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
        },
    )
    def get(self, request):
        from django.db.models import Max
        viewers = User.objects.filter(role='Viewer').annotate(
            payment_count=Count('payments', filter=Q(payments__status='Completed')),
            total_paid_rwf=Coalesce(Sum('payments__amount', filter=Q(payments__status='Completed')), 0),
            last_payment_date=Max('payments__created_at', filter=Q(payments__status='Completed')),
        )
        data = [
            {
                'id': v.id,
                'name': v.full_name,
                'payment_count': v.payment_count,
                'total_paid_rwf': v.total_paid_rwf,
                'last_payment_date': v.last_payment_date,
                'is_active': v.is_active,
            }
            for v in viewers
        ]
        return Response(data)


class AdminViewerDetailView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='Full viewer details (dispute / support use only)',
        description=(
            'Returns personal contact details for a specific viewer. '
            'Access is logged in the audit trail. '
            'This endpoint should only be accessed when investigating a payment dispute or handling a support request. '
            'Full URL: GET /api/admin/dashboard/viewers/<id>/'
        ),
        responses={
            200: inline_serializer(
                name='ViewerDetail',
                fields={
                    'id': drf_serializers.IntegerField(),
                    'name': drf_serializers.CharField(help_text='Full name'),
                    'email': drf_serializers.EmailField(allow_null=True),
                    'phone_number': drf_serializers.CharField(allow_null=True),
                    'movies_watched': drf_serializers.IntegerField(help_text='Number of completed purchases'),
                    'total_paid_rwf': drf_serializers.IntegerField(help_text='Total amount spent in RWF'),
                    'is_active': drf_serializers.BooleanField(),
                    'date_joined': drf_serializers.DateTimeField(),
                },
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
            404: OpenApiResponse(description='Viewer not found'),
        },
    )
    def get(self, request, user_id):
        viewer = (
            User.objects
            .filter(id=user_id, role='Viewer')
            .annotate(
                movies_watched=Count('payments', filter=Q(payments__status='Completed')),
                total_paid_rwf=Coalesce(Sum('payments__amount', filter=Q(payments__status='Completed')), 0),
            )
            .first()
        )
        if not viewer:
            from rest_framework.exceptions import NotFound
            raise NotFound('Viewer not found.')
        _log_admin_action(
            request, 'view_viewer_pii', target_user=viewer,
            detail={'viewer_id': viewer.id, 'reason': 'dispute/support access'},
        )
        return Response({
            'id': viewer.id,
            'name': viewer.full_name,
            'email': viewer.email,
            'phone_number': viewer.phone_number,
            'movies_watched': viewer.movies_watched,
            'total_paid_rwf': viewer.total_paid_rwf,
            'is_active': viewer.is_active,
            'date_joined': viewer.date_joined,
        })


class AdminViewerPaymentsView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary="A specific viewer's payment history",
        description=(
            'Returns all movie purchases made by the given viewer, newest first. '
            'Includes `deposit_id` and `phone_number` so admins can cross-check against '
            'PawaPay receipts when a viewer disputes a failed or missing payment.'
        ),
        responses={
            200: inline_serializer(
                name='ViewerPaymentItem',
                fields={
                    'id': drf_serializers.IntegerField(),
                    'movie_title': drf_serializers.CharField(),
                    'amount': drf_serializers.IntegerField(help_text='Amount paid in RWF'),
                    'status': drf_serializers.CharField(help_text='Pending | Completed | Failed'),
                    'deposit_id': drf_serializers.CharField(allow_null=True, help_text='PawaPay transaction reference from viewer receipt'),
                    'phone_number': drf_serializers.CharField(allow_null=True, help_text='Phone number used for the payment'),
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
        _log_admin_action(
            request, 'view_viewer_pii', target_user=user,
            detail={'viewer_id': user.id, 'reason': 'payment history / dispute lookup'},
        )
        payments = Payment.objects.filter(user=user).select_related('movie').order_by('-created_at')
        data = [
            {
                'id': p.id,
                'movie_title': p.movie.title if p.movie else 'Unknown',
                'amount': p.amount,
                'status': p.status,
                'deposit_id': p.deposit_id,
                'phone_number': p.phone_number,
                'created_at': p.created_at,
            }
            for p in payments
        ]
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

        was_active = user.is_active
        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])
        state = "activated" if user.is_active else "suspended"
        _log_admin_action(request, 'suspend_user', target_user=user,
                          detail={'was_active': was_active, 'now_active': user.is_active, 'role': user.role})
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
        _log_admin_action(request, 'delete_user',
                          detail={'deleted_email': user.email, 'deleted_phone': user.phone_number, 'deleted_role': user.role})
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
                    'address': drf_serializers.CharField(allow_blank=True),
                    'copyright_code': drf_serializers.CharField(allow_blank=True),
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
                'address': p.address,
                'copyright_code': p.copyright_code,
                'movies_uploaded': p.movies_uploaded_count,
                'total_earnings': total_earnings,
                'balance': total_earnings - locked,
                'pending_withdrawals': pending_map.get(p.id) or 0,
                'total_withdrawn': withdrawn_map.get(p.id) or 0,
                'is_active': p.is_active,
                'date_joined': p.date_joined,
            })
        return Response(data)


class AdminProducerDetailView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='Single producer detail',
        description='Returns profile, status, and wallet summary for one producer.',
        responses={
            200: inline_serializer(
                name='AdminProducerDetail',
                fields={
                    'id': drf_serializers.IntegerField(),
                    'name': drf_serializers.CharField(),
                    'email': drf_serializers.EmailField(allow_null=True),
                    'phone_number': drf_serializers.CharField(allow_null=True),
                    'address': drf_serializers.CharField(allow_blank=True),
                    'copyright_code': drf_serializers.CharField(allow_blank=True),
                    'is_active': drf_serializers.BooleanField(),
                    'date_joined': drf_serializers.DateTimeField(),
                    'total_earnings': drf_serializers.IntegerField(help_text='70% share of completed revenue (RWF)'),
                    'balance': drf_serializers.IntegerField(help_text='Available balance for withdrawal (RWF)'),
                },
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
            404: OpenApiResponse(description='Producer not found'),
        },
    )
    def get(self, request, user_id):
        producer = get_object_or_404(User, id=user_id, role='Producer')
        wallet = get_producer_wallet(producer)
        return Response({
            'id': producer.id,
            'name': producer.full_name,
            'email': producer.email,
            'phone_number': producer.phone_number,
            'address': producer.address,
            'copyright_code': producer.copyright_code,
            'is_active': producer.is_active,
            'date_joined': producer.date_joined,
            'total_earnings': wallet['total_earnings'],
            'balance': wallet['wallet_balance'],
        })


class AdminProducerMoviesView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary="All movies for one producer",
        description='Returns per-movie stats including revenue split for a given producer.',
        responses={
            200: inline_serializer(
                name='AdminProducerMovieItem',
                fields={
                    'id': drf_serializers.IntegerField(),
                    'title': drf_serializers.CharField(),
                    'views': drf_serializers.IntegerField(),
                    'total_revenue': drf_serializers.IntegerField(help_text='Sum of completed payments (RWF)'),
                    'producer_share': drf_serializers.IntegerField(help_text='70% of total_revenue (RWF)'),
                    'website_share': drf_serializers.IntegerField(help_text='30% of total_revenue (RWF)'),
                    'upload_date': drf_serializers.DateTimeField(help_text='When the movie was uploaded'),
                },
                many=True,
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
            404: OpenApiResponse(description='Producer not found'),
        },
    )
    def get(self, request, user_id):
        producer = get_object_or_404(User, id=user_id, role='Producer')
        movies = Movie.objects.filter(producer_profile=producer).annotate(
            total_revenue=Coalesce(
                Sum('payments__amount', filter=Q(payments__status='Completed')), 0
            ),
        ).order_by('-created_at')
        data = [
            {
                'id': m.id,
                'title': m.title,
                'views': m.views,
                'total_revenue': m.total_revenue,
                'producer_share': (m.total_revenue * 70) // 100,
                'website_share': m.total_revenue - (m.total_revenue * 70) // 100,
                'upload_date': m.created_at,
            }
            for m in movies
        ]
        return Response(data)


class AdminProducerReportView(AdminBaseView):
    @extend_schema(
        tags=[_REPORTS_TAG],
        summary="Audit a producer's movie performance",
        description=(
            'Returns the producer\'s wallet summary and per-movie aggregate stats. '
            'Use `GET /admin/dashboard/producers/<user_id>/movies/<movie_id>/purchases/` '
            'to page through individual purchase records with full buyer details.'
        ),
        responses={
            200: inline_serializer(
                name='AdminProducerReport',
                fields={
                    'producer': inline_serializer(
                        name='AdminProducerReportProfile',
                        fields={
                            'id': drf_serializers.IntegerField(),
                            'name': drf_serializers.CharField(),
                            'email': drf_serializers.EmailField(allow_null=True),
                            'phone_number': drf_serializers.CharField(allow_null=True),
                            'address': drf_serializers.CharField(allow_blank=True),
                            'copyright_code': drf_serializers.CharField(allow_blank=True),
                            'total_earnings': drf_serializers.IntegerField(),
                            'balance': drf_serializers.IntegerField(),
                            'pending_withdrawals': drf_serializers.IntegerField(),
                            'total_withdrawn': drf_serializers.IntegerField(),
                        },
                    ),
                    'movies': inline_serializer(
                        name='AdminProducerReportMovie',
                        fields={
                            'id': drf_serializers.IntegerField(),
                            'title': drf_serializers.CharField(),
                            'price': drf_serializers.IntegerField(),
                            'views': drf_serializers.IntegerField(),
                            'release_date': drf_serializers.DateField(),
                            'total_revenue': drf_serializers.IntegerField(help_text='Sum of completed payments (RWF)'),
                            'purchase_count': drf_serializers.IntegerField(),
                            'producer_share': drf_serializers.IntegerField(help_text='70% of total_revenue (RWF)'),
                        },
                        many=True,
                    ),
                },
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
            404: OpenApiResponse(description='Producer not found'),
        },
    )
    def get(self, request, user_id):
        producer = get_object_or_404(User, id=user_id, role='Producer')
        wallet = get_producer_wallet(producer)

        movies = Movie.objects.filter(producer_profile=producer).annotate(
            total_revenue=Coalesce(
                Sum('payments__amount', filter=Q(payments__status='Completed')), 0
            ),
            purchase_count=Count('payments', filter=Q(payments__status='Completed')),
        ).order_by('-created_at')

        movies_data = [
            {
                'id': movie.id,
                'title': movie.title,
                'price': movie.price,
                'views': movie.views,
                'release_date': movie.release_date,
                'total_revenue': movie.total_revenue,
                'purchase_count': movie.purchase_count,
                'producer_share': (movie.total_revenue * 70) // 100,
            }
            for movie in movies
        ]

        return Response({
            'producer': {
                'id': producer.id,
                'name': producer.full_name,
                'email': producer.email,
                'phone_number': producer.phone_number,
                'address': producer.address,
                'copyright_code': producer.copyright_code,
                'total_earnings': wallet['total_earnings'],
                'balance': wallet['wallet_balance'],
                'pending_withdrawals': wallet['pending_withdrawals'],
                'total_withdrawn': wallet['total_withdrawn'],
            },
            'movies': movies_data,
        })


class AdminProducerMoviePurchasesView(AdminBaseView):
    @extend_schema(
        tags=[_REPORTS_TAG],
        summary="Paginated purchase audit for a producer's movie",
        description=(
            'Returns completed purchases for a specific movie owned by the given producer, '
            'newest first, with full buyer details (name, phone, deposit ID) for commission auditing.'
        ),
        parameters=[
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
                name='AdminMoviePurchaseList',
                fields={
                    'page': drf_serializers.IntegerField(),
                    'total_results': drf_serializers.IntegerField(),
                    'total_pages': drf_serializers.IntegerField(),
                    'results': inline_serializer(
                        name='AdminMoviePurchaseItem',
                        fields={
                            'payment_id': drf_serializers.IntegerField(),
                            'buyer_name': drf_serializers.CharField(),
                            'phone_number': drf_serializers.CharField(allow_null=True),
                            'amount': drf_serializers.IntegerField(),
                            'status': drf_serializers.CharField(),
                            'deposit_id': drf_serializers.CharField(allow_null=True),
                            'purchased_at': drf_serializers.DateTimeField(),
                        },
                        many=True,
                    ),
                },
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
            404: OpenApiResponse(description='Producer or movie not found'),
        },
    )
    def get(self, request, user_id, movie_id):
        producer = get_object_or_404(User, id=user_id, role='Producer')
        movie = get_object_or_404(Movie, id=movie_id, producer_profile=producer)

        qs = (
            Payment.objects
            .filter(movie=movie, status='Completed')
            .select_related('user')
            .order_by('-created_at')
        )

        page = _safe_page(request)
        page_size = 20
        start = (page - 1) * page_size
        total = qs.count()

        results = [
            {
                'payment_id': p.id,
                'buyer_name': p.user.full_name,
                'phone_number': p.phone_number,
                'amount': p.amount,
                'status': p.status,
                'deposit_id': p.deposit_id,
                'purchased_at': p.created_at,
            }
            for p in qs[start:start + page_size]
        ]

        return Response({
            'page': page,
            'total_results': total,
            'total_pages': (total + page_size - 1) // page_size,
            'results': results,
        })


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
        _log_admin_action(request, 'approve_producer', target_user=producer,
                          detail={'producer_email': producer.email, 'producer_phone': producer.phone_number})
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
        _log_admin_action(request, 'suspend_producer', target_user=producer,
                          detail={'producer_email': producer.email, 'producer_phone': producer.phone_number})
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
                'address': drf_serializers.CharField(required=False, allow_blank=True, default=''),
                'copyright_code': drf_serializers.CharField(required=False, allow_blank=True, default=''),
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
                    'address': drf_serializers.CharField(allow_blank=True),
                    'copyright_code': drf_serializers.CharField(allow_blank=True),
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
        address = request.data.get('address', '')
        copyright_code = request.data.get('copyright_code', '')

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
        if address:
            user.address = address
        if copyright_code:
            user.copyright_code = copyright_code
        if address or copyright_code:
            user.save(update_fields=['address', 'copyright_code'])

        _log_admin_action(request, 'create_producer', target_user=user,
                          detail={'email': user.email, 'phone': user.phone_number})
        return Response({
            'id': user.id,
            'email': user.email,
            'phone_number': user.phone_number,
            'full_name': user.full_name,
            'address': user.address,
            'copyright_code': user.copyright_code,
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
            'Filter by `?status=Pending|Approved|Processing|Completed|Rejected|Failed` and/or '
            '`?producer_id=<id>` to scope results to a single producer. '
            'Without filters, all statuses and producers are returned.'
        ),
        parameters=[
            OpenApiParameter(
                name='status',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=['Pending', 'Approved', 'Processing', 'Completed', 'Rejected', 'Failed'],
                description='Filter by withdrawal status',
            ),
            OpenApiParameter(
                name='producer_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Filter by producer user ID',
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
        producer_id = request.GET.get('producer_id')
        if producer_id:
            if not producer_id.isdigit():
                return Response({'error': 'producer_id must be an integer.'}, status=status.HTTP_400_BAD_REQUEST)
            qs = qs.filter(producer_id=int(producer_id))

        page = _safe_page(request)
        page_size = 20
        start = (page - 1) * page_size
        total = qs.count()

        page_qs = list(qs[start:start + page_size])

        # Batch wallet balance calculation — 2 queries for all unique producers on this page.
        producer_ids = list({wr.producer_id for wr in page_qs})
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

        def _wallet_balance(producer_id):
            raw = revenue_map.get(producer_id) or 0
            earnings = (raw * 70) // 100
            locked = locked_map.get(producer_id) or 0
            return earnings - locked

        serialized = AdminWithdrawalRequestSerializer(page_qs, many=True).data
        results = []
        for item, wr in zip(serialized, page_qs):
            entry = dict(item)
            entry['wallet_balance'] = _wallet_balance(wr.producer_id)
            results.append(entry)

        return Response({
            'page': page,
            'results': results,
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
        _log_admin_action(request, 'approve_withdrawal', target_withdrawal=withdrawal,
                          detail={'producer': withdrawal.producer.email, 'amount': str(withdrawal.amount),
                                  'payment_method': withdrawal.payment_method})

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
            'Accepts **Pending** or **Approved** withdrawals — Pending ones are auto-approved in the '
            'same operation so admins can skip the two-step flow. '
            'Processing, Completed, Rejected, and Failed records cannot be re-completed.'
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
            400: OpenApiResponse(description='Withdrawal is in a terminal or in-flight state (Processing/Completed/Rejected/Failed)'),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
            404: OpenApiResponse(description='Withdrawal not found'),
            502: OpenApiResponse(description='PawaPay payout API error'),
        },
    )
    def post(self, request, withdrawal_id):
        withdrawal = get_object_or_404(WithdrawalRequest, id=withdrawal_id)

        _COMPLETABLE = ('Pending', 'Approved')
        _TERMINAL_MESSAGES = {
            'Processing': 'A payout is already in flight for this withdrawal.',
            'Completed':  'This withdrawal is already completed and cannot be modified.',
            'Rejected':   'This withdrawal was rejected. Create a new request to retry.',
            'Failed':     'This withdrawal failed. Create a new request to retry.',
        }
        if withdrawal.status not in _COMPLETABLE:
            return Response(
                {'error': _TERMINAL_MESSAGES.get(
                    withdrawal.status,
                    f"Cannot complete a '{withdrawal.status}' withdrawal.",
                )},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Pre-flight: validate MoMo prerequisites before any state change so that a
        # validation failure never leaves the withdrawal stranded in Approved.
        if withdrawal.payment_method == 'MoMo':
            if not withdrawal.momo_number:
                return Response(
                    {'error': 'No MoMo number on record for this withdrawal.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not detect_correspondent(withdrawal.momo_number):
                return Response(
                    {'error': f'Unrecognized Rwanda phone prefix for number: {withdrawal.momo_number}'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Auto-approve Pending withdrawals so admins can skip the two-step flow.
        # The "approved" email is intentionally suppressed — the producer will receive
        # a single completion notification below, which is the meaningful one.
        if withdrawal.status == 'Pending':
            withdrawal.status = 'Approved'
            withdrawal.save(update_fields=['status'])
            _log_admin_action(request, 'approve_withdrawal', target_withdrawal=withdrawal,
                              detail={'producer': withdrawal.producer.email, 'amount': str(withdrawal.amount),
                                      'payment_method': withdrawal.payment_method, 'auto_approved': True})

        # Bank withdrawals: mark complete immediately (manual transfer)
        if withdrawal.payment_method == 'Bank':
            withdrawal.status = 'Completed'
            withdrawal.processed_at = timezone.now()
            withdrawal.save(update_fields=['status', 'processed_at'])
            send_withdrawal_status_email(withdrawal)
            _log_admin_action(request, 'complete_withdrawal', target_withdrawal=withdrawal,
                              detail={'producer': withdrawal.producer.email, 'amount': str(withdrawal.amount),
                                      'payment_method': 'Bank'})
            return Response({
                'message': 'Withdrawal marked as completed.',
                'id': withdrawal.id,
                'status': withdrawal.status,
            })

        # MoMo withdrawals: send payout via PawaPay

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
        _log_admin_action(request, 'complete_withdrawal', target_withdrawal=withdrawal,
                          detail={'producer': withdrawal.producer.email, 'amount': str(withdrawal.amount),
                                  'payment_method': 'MoMo', 'payout_id': payout_id})

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
        _log_admin_action(request, 'reject_withdrawal', target_withdrawal=withdrawal,
                          detail={'producer': withdrawal.producer.email, 'amount': str(withdrawal.amount),
                                  'reason': request.data.get('reason', '')})

        return Response({
            'message': 'Withdrawal rejected.',
            'id': withdrawal.id,
            'status': withdrawal.status,
        })


# ─────────────────────────────────────────────
# Admin Audit Log
# ─────────────────────────────────────────────

class AdminAuditLogView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='Admin activity audit log',
        description=(
            'Returns a chronological record of all sensitive admin actions. '
            'Filter by action type with `?action=<action>`. '
            'Up to 200 most recent entries are returned.'
        ),
        parameters=[
            OpenApiParameter(
                name='action',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=[
                    'suspend_user', 'delete_user', 'approve_producer', 'suspend_producer',
                    'create_producer', 'approve_withdrawal', 'complete_withdrawal', 'reject_withdrawal',
                    'reset_user_password', 'view_viewer_pii', 'resolve_payment',
                ],
                description='Filter by action type',
            ),
        ],
        responses={
            200: inline_serializer(
                name='AuditLogResponse',
                fields={
                    'results': inline_serializer(
                        name='AuditLogEntry',
                        fields={
                            'id': drf_serializers.IntegerField(),
                            'admin': drf_serializers.EmailField(allow_null=True),
                            'action': drf_serializers.CharField(),
                            'target_user': drf_serializers.EmailField(allow_null=True),
                            'target_withdrawal_id': drf_serializers.IntegerField(allow_null=True),
                            'detail': drf_serializers.DictField(),
                            'ip_address': drf_serializers.CharField(allow_null=True),
                            'timestamp': drf_serializers.DateTimeField(),
                        },
                        many=True,
                    ),
                },
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
        },
    )
    def get(self, request):
        from apps.users.models import AdminAuditLog
        logs = AdminAuditLog.objects.select_related('admin', 'target_user').order_by('-timestamp')
        action_filter = request.query_params.get('action')
        if action_filter:
            logs = logs.filter(action=action_filter)
        data = [
            {
                'id': l.id,
                'admin': l.admin.email if l.admin else None,
                'action': l.action,
                'target_user': l.target_user.email if l.target_user else None,
                'target_withdrawal_id': l.target_withdrawal_id,
                'detail': l.detail,
                'ip_address': l.ip_address,
                'timestamp': l.timestamp,
            }
            for l in logs[:200]
        ]
        return Response({'results': data})


# ─────────────────────────────────────────────
# Analytics Reports
# ─────────────────────────────────────────────

def _safe_int(request, param, default, minimum=1, maximum=None):
    try:
        val = max(minimum, int(request.GET.get(param, default)))
        if maximum is not None:
            val = min(val, maximum)
        return val
    except (TypeError, ValueError):
        return default


class AdminRevenueTrendView(AdminBaseView):
    @extend_schema(
        tags=[_REPORTS_TAG],
        summary='Platform revenue over time',
        description=(
            'Returns revenue grouped by month or week for the last N periods. '
            'Each entry shows gross revenue, the 70% producer share, and the 30% platform commission. '
            'Periods with no sales are omitted.'
        ),
        parameters=[
            OpenApiParameter(
                name='period',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=['daily', 'weekly', 'monthly', 'yearly'],
                default='monthly',
                description='Grouping granularity',
            ),
            OpenApiParameter(
                name='periods',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                default=12,
                description=(
                    'How many periods back to include. '
                    'Defaults: daily=30, weekly=12, monthly=12, yearly=5. '
                    'Maximums: daily=90, weekly=52, monthly=36, yearly=10. '
                    'Ignored when start_date/end_date are provided.'
                ),
            ),
            OpenApiParameter(
                name='start_date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Start of date range (YYYY-MM-DD). Overrides ?periods= when provided.',
            ),
            OpenApiParameter(
                name='end_date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                required=False,
                description='End of date range inclusive (YYYY-MM-DD). Defaults to today.',
            ),
        ],
        responses={
            200: inline_serializer(
                name='AdminRevenueTrend',
                fields={
                    'period': drf_serializers.CharField(help_text='daily | weekly | monthly | yearly'),
                    'trend': inline_serializer(
                        name='AdminRevenueTrendItem',
                        fields={
                            'period_start': drf_serializers.DateTimeField(),
                            'total_revenue': drf_serializers.IntegerField(help_text='RWF'),
                            'producer_share': drf_serializers.IntegerField(help_text='70% of total_revenue (RWF)'),
                            'ikigembe_commission': drf_serializers.IntegerField(help_text='30% of total_revenue (RWF)'),
                            'purchase_count': drf_serializers.IntegerField(),
                        },
                        many=True,
                    ),
                },
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
        },
    )
    def get(self, request):
        from datetime import timedelta

        period = request.GET.get('period', 'monthly')

        # Determine trunc function and default lookback for fallback
        if period == 'daily':
            trunc_fn = TruncDay
            default_days = _safe_int(request, 'periods', 30, maximum=90)
        elif period == 'weekly':
            trunc_fn = TruncWeek
            default_days = _safe_int(request, 'periods', 12, maximum=52) * 7
        elif period == 'yearly':
            trunc_fn = TruncYear
            default_days = _safe_int(request, 'periods', 5, maximum=10) * 366
        else:
            period = 'monthly'
            trunc_fn = TruncMonth
            default_days = _safe_int(request, 'periods', 12, maximum=36) * 31

        since, until = _parse_date_range(request, default_days)

        rows = (
            Payment.objects
            .filter(status='Completed', created_at__gte=since, created_at__lte=until)
            .annotate(period_start=trunc_fn('created_at'))
            .values('period_start')
            .annotate(total_revenue=Sum('amount'), purchase_count=Count('id'))
            .order_by('period_start')
        )

        trend = []
        for row in rows:
            rev = row['total_revenue']
            producer_share = (rev * 70) // 100
            trend.append({
                'period_start': row['period_start'],
                'total_revenue': rev,
                'producer_share': producer_share,
                'ikigembe_commission': rev - producer_share,
                'purchase_count': row['purchase_count'],
            })

        return Response({'period': period, 'trend': trend})


class AdminTopMoviesView(AdminBaseView):
    @extend_schema(
        tags=[_REPORTS_TAG],
        summary='Top movies by revenue or views',
        description=(
            'Returns the top N movies ranked by completed payment revenue or by raw view count. '
            'Includes per-movie purchase count and producer name.'
        ),
        parameters=[
            OpenApiParameter(
                name='sort',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=['revenue', 'views'],
                default='revenue',
                description='Ranking metric',
            ),
            OpenApiParameter(
                name='limit',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                default=10,
                description='Number of results (default 10, max 50)',
            ),
            OpenApiParameter(
                name='start_date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Only count payments from this date (YYYY-MM-DD).',
            ),
            OpenApiParameter(
                name='end_date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Only count payments up to this date inclusive (YYYY-MM-DD).',
            ),
        ],
        responses={
            200: inline_serializer(
                name='AdminTopMovies',
                fields={
                    'sort': drf_serializers.CharField(),
                    'results': inline_serializer(
                        name='AdminTopMovieItem',
                        fields={
                            'id': drf_serializers.IntegerField(),
                            'title': drf_serializers.CharField(),
                            'producer': drf_serializers.CharField(help_text='Producer full name'),
                            'views': drf_serializers.IntegerField(),
                            'purchase_count': drf_serializers.IntegerField(),
                            'total_revenue': drf_serializers.IntegerField(help_text='Sum of completed payments (RWF)'),
                            'producer_share': drf_serializers.IntegerField(help_text='70% of total_revenue (RWF)'),
                        },
                        many=True,
                    ),
                },
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
        },
    )
    def get(self, request):
        sort = request.GET.get('sort', 'revenue')
        limit = min(_safe_int(request, 'limit', 10), 50)
        since, until = _parse_date_range(request, default_days=365)

        date_filter = Q(
            payments__status='Completed',
            payments__created_at__gte=since,
            payments__created_at__lte=until,
        )
        movies = Movie.objects.select_related('producer_profile').annotate(
            total_revenue=Coalesce(Sum('payments__amount', filter=date_filter), 0),
            purchase_count=Count('payments', filter=date_filter),
        )

        if sort == 'views':
            movies = movies.order_by('-views')
        else:
            sort = 'revenue'
            movies = movies.order_by('-total_revenue')

        results = []
        for movie in movies[:limit]:
            results.append({
                'id': movie.id,
                'title': movie.title,
                'producer': movie.producer_profile.full_name if movie.producer_profile else 'Unknown',
                'views': movie.views,
                'purchase_count': movie.purchase_count,
                'total_revenue': movie.total_revenue,
                'producer_share': (movie.total_revenue * 70) // 100,
            })

        return Response({'sort': sort, 'results': results})


class AdminUserGrowthView(AdminBaseView):
    @extend_schema(
        tags=[_REPORTS_TAG],
        summary='User registration growth over time',
        description=(
            'Returns new user registrations grouped by month for the last N months, '
            'broken down by role (Viewer, Producer). Months with no registrations are omitted.'
        ),
        parameters=[
            OpenApiParameter(
                name='months',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                default=12,
                description='How many months back to include (default 12). Ignored when start_date/end_date are provided.',
            ),
            OpenApiParameter(
                name='start_date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Start of date range (YYYY-MM-DD). Overrides ?months= when provided.',
            ),
            OpenApiParameter(
                name='end_date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                required=False,
                description='End of date range inclusive (YYYY-MM-DD). Defaults to today.',
            ),
        ],
        responses={
            200: inline_serializer(
                name='AdminUserGrowth',
                fields={
                    'trend': inline_serializer(
                        name='AdminUserGrowthItem',
                        fields={
                            'month': drf_serializers.DateTimeField(),
                            'viewers': drf_serializers.IntegerField(),
                            'producers': drf_serializers.IntegerField(),
                            'total': drf_serializers.IntegerField(),
                        },
                        many=True,
                    ),
                },
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
        },
    )
    def get(self, request):
        months = _safe_int(request, 'months', 12, maximum=24)
        since, until = _parse_date_range(request, default_days=months * 31)

        viewer_rows = {
            row['month']: row['count']
            for row in (
                User.objects
                .filter(role='Viewer', date_joined__gte=since, date_joined__lte=until)
                .annotate(month=TruncMonth('date_joined'))
                .values('month')
                .annotate(count=Count('id'))
            )
        }

        producer_rows = {
            row['month']: row['count']
            for row in (
                User.objects
                .filter(role='Producer', date_joined__gte=since, date_joined__lte=until)
                .annotate(month=TruncMonth('date_joined'))
                .values('month')
                .annotate(count=Count('id'))
            )
        }

        all_months = sorted(set(viewer_rows) | set(producer_rows))
        trend = [
            {
                'month': m,
                'viewers': viewer_rows.get(m, 0),
                'producers': producer_rows.get(m, 0),
                'total': viewer_rows.get(m, 0) + producer_rows.get(m, 0),
            }
            for m in all_months
        ]

        return Response({'trend': trend})


# ─────────────────────────────────────────────
# Report: Paying users
# ─────────────────────────────────────────────

class AdminPayingUsersReportView(AdminBaseView):
    _PAGE_SIZE = 50

    @extend_schema(
        tags=[_REPORTS_TAG],
        summary='Report of all users who have made at least one payment',
        description=(
            'Returns paginated viewers who have at least one completed payment, '
            'with contact details, total spend, purchase count, and individual payment history. '
            'Access is audit-logged. 50 users per page.'
        ),
        parameters=[
            OpenApiParameter(
                name='page',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                default=1,
                description='Page number (50 users per page)',
            ),
            OpenApiParameter(
                name='start_date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Only include payments from this date (YYYY-MM-DD).',
            ),
            OpenApiParameter(
                name='end_date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Only include payments up to this date inclusive (YYYY-MM-DD).',
            ),
        ],
        responses={
            200: inline_serializer(
                name='PayingUsersReport',
                fields={
                    'page': drf_serializers.IntegerField(),
                    'total_pages': drf_serializers.IntegerField(),
                    'total_paying_users': drf_serializers.IntegerField(),
                    'results': inline_serializer(
                        name='PayingUserItem',
                        fields={
                            'id': drf_serializers.IntegerField(),
                            'name': drf_serializers.CharField(),
                            'email': drf_serializers.EmailField(allow_null=True),
                            'phone_number': drf_serializers.CharField(allow_null=True),
                            'payment_count': drf_serializers.IntegerField(help_text='Number of completed purchases'),
                            'total_paid_rwf': drf_serializers.IntegerField(help_text='Total amount spent in RWF'),
                            'first_payment_date': drf_serializers.DateTimeField(allow_null=True),
                            'last_payment_date': drf_serializers.DateTimeField(allow_null=True),
                            'payments': inline_serializer(
                                name='PayingUserPaymentItem',
                                fields={
                                    'id': drf_serializers.IntegerField(),
                                    'movie_title': drf_serializers.CharField(),
                                    'amount': drf_serializers.IntegerField(),
                                    'status': drf_serializers.CharField(),
                                    'paid_at': drf_serializers.DateTimeField(),
                                },
                                many=True,
                            ),
                        },
                        many=True,
                    ),
                },
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
        },
    )
    def get(self, request):
        since, until = _parse_date_range(request, default_days=None)  # default: all data since 2000-01-01
        date_filter = Q(
            payments__status='Completed',
            payments__created_at__gte=since,
            payments__created_at__lte=until,
        )

        base_qs = (
            User.objects
            .filter(role='Viewer')
            .annotate(
                payment_count=Count('payments', filter=date_filter),
                total_paid_rwf=Coalesce(Sum('payments__amount', filter=date_filter), 0),
                first_payment_date=Min('payments__created_at', filter=date_filter),
                last_payment_date=Max('payments__created_at', filter=date_filter),
            )
            .filter(payment_count__gt=0)
            .order_by('-total_paid_rwf')
        )

        total = base_qs.count()
        page = _safe_page(request)
        page_size = self._PAGE_SIZE
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        start = (page - 1) * page_size
        viewers = list(base_qs[start:start + page_size])

        _log_admin_action(
            request, 'view_paying_users_report',
            detail={'page': page, 'total_paying_users': total},
        )

        # Batch-fetch completed payments for this page's viewers in one query.
        viewer_ids = [v.id for v in viewers]
        payments_by_user = {}
        for p in (
            Payment.objects
            .filter(
                user_id__in=viewer_ids,
                status='Completed',
                created_at__gte=since,
                created_at__lte=until,
            )
            .select_related('movie')
            .order_by('user_id', '-created_at')
        ):
            payments_by_user.setdefault(p.user_id, []).append({
                'id': p.id,
                'movie_title': p.movie.title if p.movie else 'Unknown',
                'amount': p.amount,
                'status': p.status,
                'paid_at': p.created_at,
            })

        results = [
            {
                'id': v.id,
                'name': v.full_name,
                'email': v.email,
                'phone_number': v.phone_number,
                'payment_count': v.payment_count,
                'total_paid_rwf': v.total_paid_rwf,
                'first_payment_date': v.first_payment_date,
                'last_payment_date': v.last_payment_date,
                'payments': payments_by_user.get(v.id, []),
            }
            for v in viewers
        ]
        return Response({
            'page': page,
            'total_pages': total_pages,
            'total_paying_users': total,
            'results': results,
        })


# ─────────────────────────────────────────────
# Admin: Force-reset a user's password
# ─────────────────────────────────────────────

class AdminUserResetPasswordView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='Generate a temporary password for a user',
        description=(
            'Generates a secure temporary password for the given user account and returns it once. '
            'Use this for phone-only accounts that cannot reset via email. '
            'The admin should share this password with the user and ask them to change it immediately. '
            'This action is recorded in the audit log.'
        ),
        request=None,
        responses={
            200: inline_serializer(
                name='ResetPasswordAdminResponse',
                fields={
                    'message': drf_serializers.CharField(),
                    'temporary_password': drf_serializers.CharField(
                        help_text='Share this with the user — it is shown only once'
                    ),
                    'user_email': drf_serializers.EmailField(allow_null=True),
                    'user_phone': drf_serializers.CharField(allow_null=True),
                },
            ),
            400: OpenApiResponse(description='Cannot reset password for an Admin account'),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
            404: OpenApiResponse(description='User not found'),
        },
    )
    def post(self, request, user_id):
        user = get_object_or_404(User, id=user_id)
        if user.role == 'Admin':
            return Response(
                {'error': 'Cannot reset password for an Admin account.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        temp_password = secrets.token_urlsafe(10)
        user.set_password(temp_password)
        # Rotate session key so all existing JWTs are immediately invalidated
        user.active_session_key = str(uuid.uuid4())
        user.save(update_fields=['password', 'active_session_key'])

        _log_admin_action(
            request, 'reset_user_password', target_user=user,
            detail={
                'user_email': user.email,
                'user_phone': user.phone_number,
                'user_role': user.role,
            },
        )

        return Response({
            'message': 'Temporary password generated. Share it with the user and ask them to change it immediately.',
            'temporary_password': temp_password,
            'user_email': user.email,
            'user_phone': user.phone_number,
        })


class AdminWithdrawalSummaryView(AdminBaseView):
    @extend_schema(
        tags=[_REPORTS_TAG],
        summary='Withdrawal payout summary by period',
        description=(
            'Returns monthly totals for withdrawal requests, broken down by status '
            '(Completed, Rejected, Pending). Useful for tracking how much was actually '
            'paid out to producers each month vs. rejected or still pending.'
        ),
        parameters=[
            OpenApiParameter(
                name='months',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                default=12,
                description='How many months back to include (default 12). Ignored when start_date/end_date are provided.',
            ),
            OpenApiParameter(
                name='start_date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Start of date range (YYYY-MM-DD). Overrides ?months= when provided.',
            ),
            OpenApiParameter(
                name='end_date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                required=False,
                description='End of date range inclusive (YYYY-MM-DD). Defaults to today.',
            ),
        ],
        responses={
            200: inline_serializer(
                name='AdminWithdrawalSummary',
                fields={
                    'trend': inline_serializer(
                        name='AdminWithdrawalSummaryItem',
                        fields={
                            'month': drf_serializers.DateTimeField(),
                            'completed': drf_serializers.IntegerField(help_text='Total paid out (RWF)'),
                            'rejected': drf_serializers.IntegerField(help_text='Total rejected (RWF)'),
                            'pending': drf_serializers.IntegerField(help_text='Total still pending (RWF)'),
                            'request_count': drf_serializers.IntegerField(),
                        },
                        many=True,
                    ),
                },
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
        },
    )
    def get(self, request):
        months = _safe_int(request, 'months', 12, maximum=24)
        since, until = _parse_date_range(request, default_days=months * 31)

        def _by_status(status_filter):
            return {
                row['month']: row['total']
                for row in (
                    WithdrawalRequest.objects
                    .filter(status=status_filter, created_at__gte=since, created_at__lte=until)
                    .annotate(month=TruncMonth('created_at'))
                    .values('month')
                    .annotate(total=Sum('amount'))
                )
            }

        completed_map = _by_status('Completed')
        rejected_map = _by_status('Rejected')
        pending_map = _by_status('Pending')

        count_map = {
            row['month']: row['count']
            for row in (
                WithdrawalRequest.objects
                .filter(created_at__gte=since, created_at__lte=until)
                .annotate(month=TruncMonth('created_at'))
                .values('month')
                .annotate(count=Count('id'))
            )
        }

        all_months = sorted(set(completed_map) | set(rejected_map) | set(pending_map))
        trend = [
            {
                'month': m,
                'completed': completed_map.get(m, 0),
                'rejected': rejected_map.get(m, 0),
                'pending': pending_map.get(m, 0),
                'request_count': count_map.get(m, 0),
            }
            for m in all_months
        ]

        return Response({'trend': trend})


# ─────────────────────────────────────────────
# Report: Genre Revenue Breakdown
# ─────────────────────────────────────────────

class AdminGenreRevenueView(AdminBaseView):
    @extend_schema(
        tags=[_REPORTS_TAG],
        summary='Revenue breakdown by genre',
        description=(
            'Returns total revenue, producer share, and purchase count grouped by movie genre. '
            'Movies may appear in multiple genres — each payment is counted once per genre on that movie. '
            'Genres with no completed payments in the date range are omitted. '
            'Sorted by total revenue descending.'
        ),
        parameters=[
            OpenApiParameter(
                name='start_date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Start of date range (YYYY-MM-DD). Defaults to 365 days ago.',
            ),
            OpenApiParameter(
                name='end_date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                required=False,
                description='End of date range inclusive (YYYY-MM-DD). Defaults to today.',
            ),
        ],
        responses={
            200: inline_serializer(
                name='AdminGenreRevenue',
                fields={
                    'results': inline_serializer(
                        name='AdminGenreRevenueItem',
                        fields={
                            'genre': drf_serializers.CharField(),
                            'total_revenue': drf_serializers.IntegerField(help_text='Sum of completed payments for movies in this genre (RWF)'),
                            'producer_share': drf_serializers.IntegerField(help_text='70% of total_revenue (RWF)'),
                            'ikigembe_commission': drf_serializers.IntegerField(help_text='30% of total_revenue (RWF)'),
                            'purchase_count': drf_serializers.IntegerField(help_text='Number of completed purchases'),
                            'movie_count': drf_serializers.IntegerField(help_text='Number of distinct movies in this genre that had sales'),
                        },
                        many=True,
                    ),
                },
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
        },
    )
    def get(self, request):
        since, until = _parse_date_range(request, default_days=365)

        # Step 1: aggregate revenue + count per movie in the DB — one row per movie,
        # not one row per payment. This is O(movies with sales) instead of O(payments).
        movie_stats = {
            row['movie_id']: {'revenue': row['total'], 'count': row['count']}
            for row in (
                Payment.objects
                .filter(
                    status='Completed',
                    created_at__gte=since,
                    created_at__lte=until,
                    movie__isnull=False,
                )
                .values('movie_id')
                .annotate(total=Sum('amount'), count=Count('id'))
            )
        }

        if not movie_stats:
            return Response({'results': []})

        # Step 2: fetch genres for only the movies that had sales — one query.
        # ORM cannot GROUP BY JSON array elements so we expand genres in Python,
        # but now we iterate movies (small set) rather than payments (large set).
        movies = Movie.objects.filter(id__in=movie_stats.keys()).values('id', 'genres')

        genre_stats = {}
        for movie in movies:
            stats = movie_stats[movie['id']]
            for genre in (movie['genres'] or []):
                if genre not in genre_stats:
                    genre_stats[genre] = {'revenue': 0, 'count': 0, 'movie_ids': set()}
                genre_stats[genre]['revenue'] += stats['revenue']
                genre_stats[genre]['count'] += stats['count']
                genre_stats[genre]['movie_ids'].add(movie['id'])

        results = []
        for genre, stats in genre_stats.items():
            producer_share, commission = producer_split(stats['revenue'])
            results.append({
                'genre': genre,
                'total_revenue': stats['revenue'],
                'producer_share': producer_share,
                'ikigembe_commission': commission,
                'purchase_count': stats['count'],
                'movie_count': len(stats['movie_ids']),
            })

        results.sort(key=lambda x: x['total_revenue'], reverse=True)
        return Response({'results': results})


# ─────────────────────────────────────────────
# Report: HLS Health
# ─────────────────────────────────────────────

class AdminHLSHealthView(AdminBaseView):
    @extend_schema(
        tags=[_REPORTS_TAG],
        summary='HLS video conversion health report',
        description=(
            'Returns a breakdown of movie HLS transcoding statuses across the platform. '
            'Highlights failed conversions (with error messages) and movies stuck in processing '
            '(with hours elapsed since conversion started). '
            '`success_rate_pct` is calculated over movies that have attempted conversion (ready + failed).'
        ),
        responses={
            200: inline_serializer(
                name='AdminHLSHealth',
                fields={
                    'summary': inline_serializer(
                        name='AdminHLSSummary',
                        fields={
                            'total_movies': drf_serializers.IntegerField(),
                            'not_started': drf_serializers.IntegerField(),
                            'processing': drf_serializers.IntegerField(),
                            'ready': drf_serializers.IntegerField(),
                            'failed': drf_serializers.IntegerField(),
                            'success_rate_pct': drf_serializers.IntegerField(help_text='ready ÷ (ready + failed) × 100; null if no conversions attempted'),
                        },
                    ),
                    'failed_movies': inline_serializer(
                        name='AdminHLSFailedMovie',
                        fields={
                            'id': drf_serializers.IntegerField(),
                            'title': drf_serializers.CharField(),
                            'producer': drf_serializers.CharField(allow_null=True),
                            'error': drf_serializers.CharField(allow_null=True),
                            'started_at': drf_serializers.DateTimeField(allow_null=True),
                        },
                        many=True,
                    ),
                    'stuck_processing': inline_serializer(
                        name='AdminHLSStuckMovie',
                        fields={
                            'id': drf_serializers.IntegerField(),
                            'title': drf_serializers.CharField(),
                            'producer': drf_serializers.CharField(allow_null=True),
                            'started_at': drf_serializers.DateTimeField(allow_null=True),
                            'hours_stuck': drf_serializers.FloatField(allow_null=True, help_text='Hours since HLS conversion started'),
                        },
                        many=True,
                    ),
                },
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
        },
    )
    def get(self, request):
        status_counts = {
            row['hls_status']: row['count']
            for row in Movie.objects.values('hls_status').annotate(count=Count('id'))
        }

        not_started = status_counts.get('not_started', 0)
        processing = status_counts.get('processing', 0)
        ready = status_counts.get('ready', 0)
        failed = status_counts.get('failed', 0)
        total = not_started + processing + ready + failed
        attempted = ready + failed
        success_rate_pct = (ready * 100 // attempted) if attempted else None

        failed_movies = [
            {
                'id': m.id,
                'title': m.title,
                'producer': m.producer_profile.full_name if m.producer_profile else None,
                'error': m.hls_error_message,
                'started_at': m.hls_started_at,
            }
            for m in Movie.objects.filter(hls_status='failed').select_related('producer_profile')
        ]

        now = timezone.now()
        stuck_processing = [
            {
                'id': m.id,
                'title': m.title,
                'producer': m.producer_profile.full_name if m.producer_profile else None,
                'started_at': m.hls_started_at,
                'hours_stuck': round((now - m.hls_started_at).total_seconds() / 3600, 1) if m.hls_started_at else None,
            }
            for m in Movie.objects.filter(hls_status='processing').select_related('producer_profile')
        ]

        return Response({
            'summary': {
                'total_movies': total,
                'not_started': not_started,
                'processing': processing,
                'ready': ready,
                'failed': failed,
                'success_rate_pct': success_rate_pct,
            },
            'failed_movies': failed_movies,
            'stuck_processing': stuck_processing,
        })


# ─────────────────────────────────────────────
# Report: Withdrawal Processing Performance
# ─────────────────────────────────────────────

class AdminWithdrawalPerformanceView(AdminBaseView):
    @extend_schema(
        tags=[_REPORTS_TAG],
        summary='Withdrawal payout processing performance',
        description=(
            'Returns processing speed and success rates for withdrawal requests that have been actioned '
            '(approved, completed, rejected, or failed). '
            'Broken down overall and by payment method (Bank / MoMo). '
            '`avg_processing_hours` measures time from request creation to final action.'
        ),
        parameters=[
            OpenApiParameter(
                name='start_date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Start of date range (YYYY-MM-DD). Defaults to 90 days ago.',
            ),
            OpenApiParameter(
                name='end_date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                required=False,
                description='End of date range inclusive (YYYY-MM-DD). Defaults to today.',
            ),
        ],
        responses={
            200: inline_serializer(
                name='AdminWithdrawalPerformance',
                fields={
                    'overall': inline_serializer(
                        name='AdminWithdrawalPerformanceOverall',
                        fields={
                            'total_processed': drf_serializers.IntegerField(),
                            'completed': drf_serializers.IntegerField(),
                            'rejected': drf_serializers.IntegerField(),
                            'failed': drf_serializers.IntegerField(),
                            'success_rate_pct': drf_serializers.IntegerField(allow_null=True),
                            'avg_processing_hours': drf_serializers.FloatField(allow_null=True, help_text='Average hours from creation to final status'),
                        },
                    ),
                    'by_method': drf_serializers.DictField(
                        help_text='Stats keyed by payment_method (Bank, MoMo)',
                        child=inline_serializer(
                            name='AdminWithdrawalMethodStats',
                            fields={
                                'count': drf_serializers.IntegerField(),
                                'completed': drf_serializers.IntegerField(),
                                'rejected': drf_serializers.IntegerField(),
                                'failed': drf_serializers.IntegerField(),
                                'success_rate_pct': drf_serializers.IntegerField(allow_null=True),
                                'avg_processing_hours': drf_serializers.FloatField(allow_null=True),
                            },
                        ),
                    ),
                },
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
        },
    )
    def get(self, request):
        since, until = _parse_date_range(request, default_days=90)

        # Only include terminal statuses so total_processed, success_rate_pct, and
        # avg_processing_hours are all computed over the same consistent set of records.
        # Approved/Processing have processed_at set but are not yet resolved — including
        # them would inflate total_processed while the success/failure counts stay lower.
        qs = list(
            WithdrawalRequest.objects
            .filter(
                status__in=['Completed', 'Rejected', 'Failed'],
                processed_at__isnull=False,
                created_at__gte=since,
                created_at__lte=until,
            )
            .only('status', 'payment_method', 'created_at', 'processed_at')
        )

        def _aggregate(records):
            if not records:
                return {
                    'count': 0, 'completed': 0, 'rejected': 0, 'failed': 0,
                    'success_rate_pct': None, 'avg_processing_hours': None,
                }
            completed = sum(1 for r in records if r.status == 'Completed')
            rejected = sum(1 for r in records if r.status == 'Rejected')
            failed = sum(1 for r in records if r.status == 'Failed')
            total = len(records)
            terminal = completed + rejected + failed
            success_rate_pct = (completed * 100 // terminal) if terminal else None
            deltas = [
                (r.processed_at - r.created_at).total_seconds() / 3600
                for r in records
                if r.processed_at and r.created_at
            ]
            avg_hours = round(sum(deltas) / len(deltas), 1) if deltas else None
            return {
                'count': total,
                'completed': completed,
                'rejected': rejected,
                'failed': failed,
                'success_rate_pct': success_rate_pct,
                'avg_processing_hours': avg_hours,
            }

        overall = _aggregate(qs)
        overall['total_processed'] = overall.pop('count')

        by_method = {}
        for method in ('Bank', 'MoMo'):
            subset = [r for r in qs if r.payment_method == method]
            if subset:
                by_method[method] = _aggregate(subset)

        return Response({'overall': overall, 'by_method': by_method})


# ─────────────────────────────────────────────
# Payment Dispute: Lookup & Manual Resolution
# ─────────────────────────────────────────────

class AdminPaymentLookupView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='Look up a payment by deposit ID or phone number',
        description=(
            'Finds a payment record using the PawaPay `deposit_id` from the viewer\'s MoMo receipt, '
            'or by the `phone_number` used during payment. '
            'Use this when a viewer claims they paid but their access is not granted. '
            'At least one of `deposit_id` or `phone_number` must be provided.'
        ),
        parameters=[
            OpenApiParameter(
                name='deposit_id',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description='PawaPay deposit ID from the viewer\'s MoMo receipt',
            ),
            OpenApiParameter(
                name='phone_number',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Phone number used during payment (e.g. 250788123456)',
            ),
        ],
        responses={
            200: inline_serializer(
                name='PaymentLookupResponse',
                fields={
                    'results': inline_serializer(
                        name='PaymentLookupItem',
                        fields={
                            'id': drf_serializers.IntegerField(),
                            'viewer_id': drf_serializers.IntegerField(),
                            'viewer_name': drf_serializers.CharField(),
                            'viewer_email': drf_serializers.EmailField(allow_null=True),
                            'viewer_phone': drf_serializers.CharField(allow_null=True),
                            'movie_id': drf_serializers.IntegerField(allow_null=True),
                            'movie_title': drf_serializers.CharField(),
                            'amount': drf_serializers.IntegerField(help_text='RWF'),
                            'status': drf_serializers.CharField(help_text='Pending | Completed | Failed'),
                            'deposit_id': drf_serializers.CharField(allow_null=True),
                            'phone_number': drf_serializers.CharField(allow_null=True, help_text='Phone used for payment'),
                            'created_at': drf_serializers.DateTimeField(),
                        },
                        many=True,
                    ),
                },
            ),
            400: OpenApiResponse(description='Neither deposit_id nor phone_number provided'),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
        },
    )
    def get(self, request):
        deposit_id = request.GET.get('deposit_id', '').strip()
        phone_number = request.GET.get('phone_number', '').strip()

        if not deposit_id and not phone_number:
            return Response(
                {'error': 'Provide at least one of deposit_id or phone_number.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Build filter from whichever params are present (AND when both supplied).
        # deposit_id is unique-indexed — exact match is instant.
        # phone_number uses startswith so a numeric prefix scan is selective enough
        # without a full-table icontains scan.
        filters = Q()
        if deposit_id:
            filters &= Q(deposit_id=deposit_id)
        if phone_number:
            filters &= Q(phone_number__startswith=phone_number)

        qs = (
            Payment.objects
            .filter(filters)
            .select_related('user', 'movie')
            .order_by('-created_at')[:50]
        )

        results = [
            {
                'id': p.id,
                'viewer_id': p.user_id,
                'viewer_name': p.user.full_name if p.user else '',
                'viewer_email': p.user.email if p.user else None,
                'viewer_phone': p.user.phone_number if p.user else None,
                'movie_id': p.movie_id,
                'movie_title': p.movie.title if p.movie else 'Unknown',
                'amount': p.amount,
                'status': p.status,
                'deposit_id': p.deposit_id,
                'phone_number': p.phone_number,
                'created_at': p.created_at,
            }
            for p in qs
        ]

        return Response({'results': results})


class AdminPaymentResolveView(AdminBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='Manually resolve a disputed payment',
        description=(
            'Marks a `Pending` or `Failed` payment as `Completed`, immediately granting the viewer '
            'access to the movie. Use this when a viewer provides proof of payment (MoMo receipt, '
            'PawaPay transaction ID) and the system failed to update the status automatically. '
            'A `reason` is required and the action is recorded in the audit log.'
        ),
        request=inline_serializer(
            name='PaymentResolveRequest',
            fields={
                'reason': drf_serializers.CharField(
                    help_text='Why this payment is being manually resolved (e.g. "Viewer provided MoMo receipt ref TX123, webhook missed")'
                ),
            },
        ),
        responses={
            200: inline_serializer(
                name='PaymentResolveResponse',
                fields={
                    'message': drf_serializers.CharField(),
                    'payment_id': drf_serializers.IntegerField(),
                    'viewer': drf_serializers.CharField(),
                    'movie': drf_serializers.CharField(),
                    'status': drf_serializers.CharField(help_text='Always "Completed" after resolution'),
                },
            ),
            400: OpenApiResponse(description='Payment is already Completed, or reason not provided'),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Admin role required'),
            404: OpenApiResponse(description='Payment not found'),
        },
    )
    def post(self, request, payment_id):
        payment = get_object_or_404(Payment, id=payment_id)

        if payment.status == 'Completed':
            return Response(
                {'error': 'Payment is already Completed — viewer already has access.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reason = (request.data.get('reason') or '').strip()
        if not reason:
            return Response(
                {'error': 'A reason is required to manually resolve a payment.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        previous_status = payment.status
        payment.status = 'Completed'
        payment.save(update_fields=['status'])

        send_payment_completed_email(payment)

        _log_admin_action(
            request,
            'resolve_payment',
            target_user=payment.user,
            detail={
                'payment_id': payment.id,
                'previous_status': previous_status,
                'deposit_id': payment.deposit_id,
                'movie': payment.movie.title if payment.movie else None,
                'viewer_email': payment.user.email if payment.user else None,
                'amount_rwf': payment.amount,
                'reason': reason,
            },
        )

        return Response({
            'message': 'Payment resolved. Viewer now has access to the movie.',
            'payment_id': payment.id,
            'viewer': payment.user.full_name or payment.user.email or str(payment.user_id),
            'movie': payment.movie.title if payment.movie else 'Unknown',
            'status': payment.status,
        })


# ─────────────────────────────────────────────────────────────────────────────
# Movie Subtitle Management — Admin only
# ─────────────────────────────────────────────────────────────────────────────

class AdminMovieSubtitleListView(AdminBaseView):
    """
    POST /api/admin/dashboard/movies/<movie_id>/subtitles/
    Upload a new subtitle track for a movie.
    Concurrent duplicate requests are handled atomically — the unique_together
    constraint raises IntegrityError which is converted to 409.
    """
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        tags=[_TAG],
        summary='Upload a subtitle track',
        description=(
            'Upload a .vtt or .srt subtitle file for a specific language. '
            'Send as **multipart/form-data** with fields: `language_code`, `subtitle_file`, '
            '`is_default` (optional, default False), `ordering` (optional, default 0). '
            'Only one track per language_code per movie is permitted. '
            'Delete the existing track first if you need to replace the file.'
        ),
        request={'multipart/form-data': SubtitleUploadSerializer},
        responses={
            201: SubtitleSerializer,
            400: OpenApiResponse(description='Validation error'),
            403: OpenApiResponse(description='Admin access required'),
            404: OpenApiResponse(description='Movie not found'),
            409: OpenApiResponse(description='A subtitle track for this language already exists'),
        },
    )
    def post(self, request, movie_id):
        try:
            movie = Movie.objects.get(id=movie_id)
        except Movie.DoesNotExist:
            return Response({'error': 'Movie not found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = SubtitleUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                subtitle = serializer.save(movie=movie)
        except IntegrityError:
            lang = request.data.get('language_code', '')
            return Response(
                {'error': f'A subtitle track for "{lang}" already exists. Delete it first to replace it.'},
                status=status.HTTP_409_CONFLICT,
            )

        _log_admin_action(
            request,
            'upload_subtitle',
            detail={
                'movie_id': movie.id,
                'movie_title': movie.title,
                'language_code': subtitle.language_code,
                'language_name': subtitle.language_name,
                'is_default': subtitle.is_default,
            },
        )
        return Response(SubtitleSerializer(subtitle).data, status=status.HTTP_201_CREATED)


class AdminMovieSubtitleDetailView(AdminBaseView):
    """
    PATCH  /api/admin/dashboard/movies/<movie_id>/subtitles/<subtitle_id>/
    DELETE /api/admin/dashboard/movies/<movie_id>/subtitles/<subtitle_id>/
    Update metadata or remove a subtitle track.
    """

    def _get_subtitle(self, movie_id, subtitle_id):
        try:
            return Subtitle.objects.select_related('movie').get(id=subtitle_id, movie_id=movie_id)
        except Subtitle.DoesNotExist:
            return None

    @extend_schema(
        tags=[_TAG],
        summary='Update a subtitle track',
        description=(
            'Partially update a subtitle track — change language_code, language_name, '
            'set/unset is_default, or adjust ordering. '
            'To replace the subtitle file, delete this track and re-upload.'
        ),
        request=SubtitleUpdateSerializer,
        responses={
            200: SubtitleSerializer,
            400: OpenApiResponse(description='Validation error'),
            403: OpenApiResponse(description='Admin access required'),
            404: OpenApiResponse(description='Subtitle not found'),
        },
    )
    def patch(self, request, movie_id, subtitle_id):
        subtitle = self._get_subtitle(movie_id, subtitle_id)
        if subtitle is None:
            return Response({'error': 'Subtitle not found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = SubtitleUpdateSerializer(subtitle, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer.save()
        subtitle.refresh_from_db()

        _log_admin_action(
            request,
            'update_subtitle',
            detail={
                'subtitle_id': subtitle.id,
                'movie_id': subtitle.movie_id,
                'movie_title': subtitle.movie.title,
                'changes': request.data,
            },
        )
        return Response(SubtitleSerializer(subtitle).data)

    @extend_schema(
        tags=[_TAG],
        summary='Delete a subtitle track',
        description='Removes a subtitle track record. The S3 file is NOT automatically deleted.',
        responses={
            204: OpenApiResponse(description='Deleted'),
            403: OpenApiResponse(description='Admin access required'),
            404: OpenApiResponse(description='Subtitle not found'),
        },
    )
    def delete(self, request, movie_id, subtitle_id):
        subtitle = self._get_subtitle(movie_id, subtitle_id)
        if subtitle is None:
            return Response({'error': 'Subtitle not found'}, status=status.HTTP_404_NOT_FOUND)

        _log_admin_action(
            request,
            'delete_subtitle',
            detail={
                'subtitle_id': subtitle.id,
                'movie_id': subtitle.movie_id,
                'movie_title': subtitle.movie.title,
                'language_code': subtitle.language_code,
            },
        )
        subtitle.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
