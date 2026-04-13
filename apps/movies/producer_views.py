from django.db import transaction
from django.db.models import Sum, Count, Q
from django.db.models.functions import Coalesce, TruncDay, TruncMonth, TruncWeek
from django.utils import timezone
from datetime import timedelta
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status, serializers as drf_serializers
from drf_spectacular.utils import extend_schema, inline_serializer, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from apps.users.permissions import IsProducerRole
from apps.movies.models import Movie, WatchProgress
from apps.movies.serializers import ProducerMovieListSerializer, ProducerMovieDetailSerializer
from apps.payments.models import Payment, WithdrawalRequest
from apps.payments.serializers import WithdrawalRequestSerializer, get_producer_wallet, producer_split


def _safe_page(request):
    """Return a valid page number from ?page=, defaulting to 1 for any invalid input."""
    try:
        return max(1, int(request.GET.get('page', 1)))
    except (TypeError, ValueError):
        return 1

_TAG = 'Producer Dashboard'
_REPORTS_TAG = 'Producer Reports'


class ProducerBaseView(APIView):
    permission_classes = [IsAuthenticated, IsProducerRole]


class ProducerMyMoviesView(ProducerBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='List my movies',
        description=(
            'Returns all movies belonging to the authenticated producer, ordered by most recently added. '
            'Read-only — uploading, editing, and deleting movies is handled by the Admin.'
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
                name='ProducerMovieListResponse',
                fields={
                    'page': drf_serializers.IntegerField(),
                    'total_results': drf_serializers.IntegerField(),
                    'total_pages': drf_serializers.IntegerField(),
                    'results': ProducerMovieListSerializer(many=True),
                },
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Producer role required'),
        },
    )
    def get(self, request):
        movies = Movie.objects.filter(
            producer_profile=request.user
        ).order_by('-created_at')

        page = _safe_page(request)
        page_size = 20
        start = (page - 1) * page_size
        total = movies.count()

        return Response({
            'page': page,
            'results': ProducerMovieListSerializer(movies[start:start + page_size], many=True).data,
            'total_results': total,
            'total_pages': (total + page_size - 1) // page_size,
        })


class ProducerMovieDetailView(ProducerBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='Get full details of one of my movies',
        description=(
            'Returns all metadata, file URLs, and HLS transcoding status for a movie '
            'owned by the authenticated producer. Returns 404 if the movie does not belong to them.'
        ),
        responses={
            200: ProducerMovieDetailSerializer,
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Producer role required'),
            404: OpenApiResponse(description='Movie not found or not owned by this producer'),
        },
    )
    def get(self, request, id):
        try:
            movie = Movie.objects.get(id=id, producer_profile=request.user)
        except Movie.DoesNotExist:
            return Response({'error': 'Movie not found'}, status=status.HTTP_404_NOT_FOUND)
        return Response(ProducerMovieDetailSerializer(movie).data)


class ProducerWalletView(ProducerBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='Get my wallet balance',
        description=(
            'Returns the producer\'s earnings breakdown in real-time. '
            'All figures are in RWF. '
            '`wallet_balance` is what is currently available to withdraw.'
        ),
        responses={
            200: inline_serializer(
                name='ProducerWallet',
                fields={
                    'gross_revenue': drf_serializers.IntegerField(help_text='Total completed payment revenue from your movies (RWF)'),
                    'ikigembe_commission': drf_serializers.IntegerField(help_text='30% platform commission deducted from gross revenue (RWF)'),
                    'total_earnings': drf_serializers.IntegerField(help_text='Your 70% share of gross revenue (RWF)'),
                    'wallet_balance': drf_serializers.IntegerField(help_text='Available balance — total_earnings minus locked/paid amounts (RWF)'),
                    'pending_withdrawals': drf_serializers.IntegerField(help_text='Amount locked in pending withdrawal requests (RWF)'),
                    'total_withdrawn': drf_serializers.IntegerField(help_text='Total amount paid out so far (RWF)'),
                },
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Producer role required'),
        },
    )
    def get(self, request):
        return Response(get_producer_wallet(request.user))


class ProducerReportView(ProducerBaseView):
    @extend_schema(
        tags=[_REPORTS_TAG],
        summary='My movies performance report',
        description=(
            'Returns the authenticated producer\'s wallet summary alongside per-movie aggregate stats: '
            'view count, purchase count, total revenue, and the producer\'s 70% share. '
            'Use `GET /producer/movies/<id>/purchases/` to page through individual purchase records.'
        ),
        responses={
            200: inline_serializer(
                name='ProducerReport',
                fields={
                    'wallet': inline_serializer(
                        name='ProducerReportWallet',
                        fields={
                            'total_earnings': drf_serializers.IntegerField(),
                            'wallet_balance': drf_serializers.IntegerField(),
                            'pending_withdrawals': drf_serializers.IntegerField(),
                            'total_withdrawn': drf_serializers.IntegerField(),
                        },
                    ),
                    'movies': inline_serializer(
                        name='ProducerReportMovie',
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
            403: OpenApiResponse(description='Producer role required'),
        },
    )
    def get(self, request):
        wallet = get_producer_wallet(request.user)
        movies = Movie.objects.filter(producer_profile=request.user).annotate(
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
            'wallet': wallet,
            'movies': movies_data,
        })



class ProducerWithdrawalsView(ProducerBaseView):
    @extend_schema(
        tags=[_TAG],
        summary='List my withdrawal requests',
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
                name='ProducerWithdrawalListResponse',
                fields={
                    'page': drf_serializers.IntegerField(),
                    'total_results': drf_serializers.IntegerField(),
                    'total_pages': drf_serializers.IntegerField(),
                    'results': WithdrawalRequestSerializer(many=True),
                },
            ),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Producer role required'),
        },
    )
    def get(self, request):
        qs = WithdrawalRequest.objects.filter(producer=request.user)
        page = _safe_page(request)
        page_size = 20
        start = (page - 1) * page_size
        total = qs.count()
        return Response({
            'page': page,
            'results': WithdrawalRequestSerializer(qs[start:start + page_size], many=True).data,
            'total_results': total,
            'total_pages': (total + page_size - 1) // page_size,
        })

    @extend_schema(
        tags=[_TAG],
        summary='Request a payout',
        description=(
            'Submit a withdrawal request. Amount must not exceed your current `wallet_balance`. '
            'Provide either Bank details (`bank_name`, `account_number`, `account_holder_name`) '
            'or MoMo details (`momo_number`, `momo_provider`) depending on `payment_method`.'
        ),
        request=WithdrawalRequestSerializer,
        responses={
            201: WithdrawalRequestSerializer,
            400: OpenApiResponse(description='Validation error or amount exceeds wallet balance'),
            401: OpenApiResponse(description='Authentication credentials not provided'),
            403: OpenApiResponse(description='Producer role required'),
        },
    )
    def post(self, request):
        serializer = WithdrawalRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        amount = serializer.validated_data['amount']

        # Hold a row-level lock on all non-rejected withdrawal rows for this
        # producer before computing the available balance.  Without this lock,
        # two concurrent requests can both read the same balance, both pass the
        # check, and together overspend (TOCTOU race).
        with transaction.atomic():
            locked = WithdrawalRequest.objects.select_for_update().filter(
                producer=request.user,
                status__in=['Pending', 'Approved', 'Processing', 'Completed'],
            ).aggregate(total=Coalesce(Sum('amount'), 0))['total']

            raw_revenue = Payment.objects.filter(
                movie__producer_profile=request.user,
                status='Completed',
            ).aggregate(total=Coalesce(Sum('amount'), 0))['total']

            balance = producer_split(raw_revenue)[0] - locked

            if amount > balance:
                return Response(
                    {'error': f"Amount exceeds available balance of {balance} RWF."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            serializer.save(producer=request.user, status='Pending')

        return Response(serializer.data, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────
# Per-movie Analytics
# ─────────────────────────────────────────────

class ProducerMovieAnalyticsView(ProducerBaseView):
    @extend_schema(
        tags=[_REPORTS_TAG],
        summary='Analytics for one of my movies',
        description=(
            'Returns view count, revenue breakdown (gross / 30% commission / 70% earnings), '
            'total buyers, and a paginated list of individual purchases for a specific movie.'
        ),
        parameters=[
            OpenApiParameter('page', OpenApiTypes.INT, OpenApiParameter.QUERY,
                             required=False, default=1, description='Page number (20 per page)'),
        ],
        responses={
            200: inline_serializer(
                name='MovieAnalytics',
                fields={
                    'movie_id': drf_serializers.IntegerField(),
                    'title': drf_serializers.CharField(),
                    'views': drf_serializers.IntegerField(),
                    'total_buyers': drf_serializers.IntegerField(help_text='Number of completed purchases'),
                    'gross_revenue': drf_serializers.IntegerField(help_text='Sum of all completed payments (RWF)'),
                    'ikigembe_commission': drf_serializers.IntegerField(help_text='30% platform share (RWF)'),
                    'producer_earnings': drf_serializers.IntegerField(help_text='70% producer share (RWF)'),
                    'watch_stats': inline_serializer(
                        name='WatchStats',
                        fields={
                            'total_watchers': drf_serializers.IntegerField(help_text='Users who started watching'),
                            'completed_count': drf_serializers.IntegerField(help_text='Users who finished the movie'),
                            'completion_rate_pct': drf_serializers.FloatField(help_text='% of watchers who finished'),
                            'avg_progress_pct': drf_serializers.FloatField(help_text='Average % of the movie watched across all watchers'),
                        },
                    ),
                    'page': drf_serializers.IntegerField(),
                    'total_results': drf_serializers.IntegerField(),
                    'total_pages': drf_serializers.IntegerField(),
                    'buyers': inline_serializer(
                        name='BuyerEntry',
                        fields={
                            'buyer_name': drf_serializers.CharField(),
                            'amount_paid': drf_serializers.IntegerField(help_text='RWF'),
                            'purchased_at': drf_serializers.DateTimeField(),
                        },
                        many=True,
                    ),
                },
            ),
            403: OpenApiResponse(description='Producer role required'),
            404: OpenApiResponse(description='Movie not found or not owned by this producer'),
        },
    )
    def get(self, request, id):
        try:
            movie = Movie.objects.get(id=id, producer_profile=request.user)
        except Movie.DoesNotExist:
            return Response({'error': 'Movie not found'}, status=status.HTTP_404_NOT_FOUND)

        payments = Payment.objects.filter(
            movie=movie, status='Completed'
        ).select_related('user').order_by('-created_at')

        gross = payments.aggregate(total=Coalesce(Sum('amount'), 0))['total']
        earnings, commission = producer_split(gross)

        page = _safe_page(request)
        page_size = 20
        start = (page - 1) * page_size
        total = payments.count()

        buyers = [
            {
                'buyer_name': p.user.full_name or p.user.email or p.user.phone_number,
                'amount_paid': p.amount,
                'purchased_at': p.created_at,
            }
            for p in payments[start:start + page_size]
        ]

        # Watch completion stats from WatchProgress
        watch_qs = WatchProgress.objects.filter(movie=movie)
        total_watchers = watch_qs.count()
        completed_count = watch_qs.filter(completed=True).count()
        completion_rate_pct = round(completed_count * 100 / total_watchers, 1) if total_watchers else 0.0
        timed_records = list(watch_qs.filter(duration_seconds__gt=0).values_list('progress_seconds', 'duration_seconds'))
        avg_progress_pct = round(
            sum(p / d * 100 for p, d in timed_records) / len(timed_records), 1
        ) if timed_records else 0.0

        return Response({
            'movie_id': movie.id,
            'title': movie.title,
            'views': movie.views,
            'total_buyers': total,
            'gross_revenue': gross,
            'ikigembe_commission': commission,
            'producer_earnings': earnings,
            'watch_stats': {
                'total_watchers': total_watchers,
                'completed_count': completed_count,
                'completion_rate_pct': completion_rate_pct,
                'avg_progress_pct': avg_progress_pct,
            },
            'page': page,
            'total_results': total,
            'total_pages': (total + page_size - 1) // page_size,
            'buyers': buyers,
        })


# ─────────────────────────────────────────────
# Earnings Report (daily / weekly / monthly)
# ─────────────────────────────────────────────

class ProducerEarningsReportView(ProducerBaseView):
    @extend_schema(
        tags=[_REPORTS_TAG],
        summary='Earnings report by period',
        description=(
            'Returns earnings grouped by day (last 30 days), week (last 12 weeks), '
            'or month (last 12 months). Each bucket shows gross revenue, '
            'Ikigembe 30% commission, and the producer\'s 70% net earnings.'
        ),
        parameters=[
            OpenApiParameter(
                name='period',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=['daily', 'weekly', 'monthly'],
                default='monthly',
                description='Grouping period',
            ),
        ],
        responses={
            200: inline_serializer(
                name='EarningsReport',
                fields={
                    'period': drf_serializers.CharField(help_text='daily | weekly | monthly'),
                    'results': inline_serializer(
                        name='EarningsBucket',
                        fields={
                            'period_start': drf_serializers.DateTimeField(),
                            'gross_revenue': drf_serializers.IntegerField(help_text='RWF'),
                            'ikigembe_commission': drf_serializers.IntegerField(help_text='30% (RWF)'),
                            'producer_earnings': drf_serializers.IntegerField(help_text='70% (RWF)'),
                            'transactions': drf_serializers.IntegerField(help_text='Number of completed purchases'),
                        },
                        many=True,
                    ),
                },
            ),
            403: OpenApiResponse(description='Producer role required'),
        },
    )
    def get(self, request):
        period = request.query_params.get('period', 'monthly')
        now = timezone.now()

        if period == 'daily':
            trunc_fn = TruncDay
            cutoff = now - timezone.timedelta(days=30)
        elif period == 'weekly':
            trunc_fn = TruncWeek
            cutoff = now - timezone.timedelta(weeks=12)
        else:
            period = 'monthly'
            trunc_fn = TruncMonth
            cutoff = now - timezone.timedelta(days=365)

        rows = (
            Payment.objects.filter(
                movie__producer_profile=request.user,
                status='Completed',
                created_at__gte=cutoff,
            )
            .annotate(bucket=trunc_fn('created_at'))
            .values('bucket')
            .annotate(gross=Coalesce(Sum('amount'), 0), count=Count('id'))
            .order_by('bucket')
        )

        results = []
        for row in rows:
            gross = row['gross']
            earnings, commission = producer_split(gross)
            results.append({
                'period_start': row['bucket'],
                'gross_revenue': gross,
                'ikigembe_commission': commission,
                'producer_earnings': earnings,
                'transactions': row['count'],
            })

        return Response({'period': period, 'results': results})


# ─────────────────────────────────────────────
# Transaction History (payments in + withdrawals out)
# ─────────────────────────────────────────────

class ProducerTransactionHistoryView(ProducerBaseView):
    @extend_schema(
        tags=[_REPORTS_TAG],
        summary='My transaction history',
        description=(
            'Returns two DB-paginated sections: completed incoming payments and all withdrawal '
            'requests. Only Completed payments are included in the earnings section. '
            'Use the `?page` parameter for both sections simultaneously.'
        ),
        parameters=[
            OpenApiParameter('page', OpenApiTypes.INT, OpenApiParameter.QUERY,
                             required=False, default=1, description='Page number (20 per page)'),
        ],
        responses={
            200: inline_serializer(
                name='TransactionHistoryResponse',
                fields={
                    'payments': inline_serializer(
                        name='PaymentTransactionSection',
                        fields={
                            'page': drf_serializers.IntegerField(),
                            'total_results': drf_serializers.IntegerField(),
                            'total_pages': drf_serializers.IntegerField(),
                            'results': inline_serializer(
                                name='IncomingPaymentEntry',
                                fields={
                                    'id': drf_serializers.IntegerField(),
                                    'movie_title': drf_serializers.CharField(),
                                    'gross_amount': drf_serializers.IntegerField(help_text='Full payment amount (RWF)'),
                                    'producer_earnings': drf_serializers.IntegerField(help_text='Your 70% share (RWF)'),
                                    'date': drf_serializers.DateTimeField(),
                                },
                                many=True,
                            ),
                        },
                    ),
                    'withdrawals': inline_serializer(
                        name='WithdrawalTransactionSection',
                        fields={
                            'page': drf_serializers.IntegerField(),
                            'total_results': drf_serializers.IntegerField(),
                            'total_pages': drf_serializers.IntegerField(),
                            'results': WithdrawalRequestSerializer(many=True),
                        },
                    ),
                },
            ),
            403: OpenApiResponse(description='Producer role required'),
        },
    )
    def get(self, request):
        page = _safe_page(request)
        page_size = 20
        start = (page - 1) * page_size

        # Completed payments only — consistent with all other financial endpoints
        payments_qs = Payment.objects.filter(
            movie__producer_profile=request.user,
            status='Completed',
        ).select_related('movie').order_by('-created_at')

        payments_total = payments_qs.count()
        payment_entries = []
        for p in payments_qs[start:start + page_size]:
            earnings, _ = producer_split(p.amount)
            payment_entries.append({
                'id': p.id,
                'movie_title': p.movie.title if p.movie else 'Unknown',
                'gross_amount': p.amount,
                'producer_earnings': earnings,
                'date': p.created_at,
            })

        withdrawals_qs = WithdrawalRequest.objects.filter(
            producer=request.user,
        ).order_by('-created_at')

        withdrawals_total = withdrawals_qs.count()

        return Response({
            'payments': {
                'page': page,
                'total_results': payments_total,
                'total_pages': (payments_total + page_size - 1) // page_size,
                'results': payment_entries,
            },
            'withdrawals': {
                'page': page,
                'total_results': withdrawals_total,
                'total_pages': (withdrawals_total + page_size - 1) // page_size,
                'results': WithdrawalRequestSerializer(
                    withdrawals_qs[start:start + page_size], many=True
                ).data,
            },
        })
