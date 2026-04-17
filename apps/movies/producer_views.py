import csv
from django.db import transaction
from django.db.models import Sum, Count, Q, Avg, ExpressionWrapper, FloatField, F
from django.db.models.functions import Coalesce, TruncDay, TruncMonth, TruncWeek
from django.http import HttpResponse
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


def _csv_response(filename, headers, rows):
    """Return a CSV file download response."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(headers)
    writer.writerows(rows)
    return response


def _safe_page(request):
    """Return a valid page number from ?page=, defaulting to 1 for any invalid input."""
    try:
        return max(1, int(request.GET.get('page', 1)))
    except (TypeError, ValueError):
        return 1


def _parse_date_range(request, default_days=365):
    """Parse ?start_date= and ?end_date= (YYYY-MM-DD). Defaults to last `default_days` days."""
    from datetime import datetime
    since = until = None
    try:
        since = timezone.make_aware(datetime.strptime(request.GET.get('start_date', ''), '%Y-%m-%d'))
    except ValueError:
        pass
    try:
        until = timezone.make_aware(
            datetime.strptime(request.GET.get('end_date', ''), '%Y-%m-%d')
            .replace(hour=23, minute=59, second=59, microsecond=999999)
        )
    except ValueError:
        pass
    if until is None:
        until = timezone.now()
    if since is None:
        since = until - timedelta(days=default_days)
    return since, until

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
                    'platform_commission': drf_serializers.IntegerField(help_text='30% platform commission deducted from gross revenue (RWF)'),
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
            'Returns the producer\'s wallet summary alongside per-movie content performance '
            'and earnings data. Revenue stats are filterable by date range; watch engagement '
            'metrics (watch time, completion rate) are lifetime totals. '
            'Add ?export=csv to download the movies table as a CSV file.'
        ),
        parameters=[
            OpenApiParameter('start_date', OpenApiTypes.DATE, OpenApiParameter.QUERY,
                             required=False, description='Filter revenue from this date (YYYY-MM-DD)'),
            OpenApiParameter('end_date', OpenApiTypes.DATE, OpenApiParameter.QUERY,
                             required=False, description='Filter revenue up to this date inclusive (YYYY-MM-DD)'),
            OpenApiParameter('export', OpenApiTypes.STR, OpenApiParameter.QUERY,
                             required=False, enum=['csv'], description='Set to "csv" to download as CSV'),
        ],
        responses={
            200: inline_serializer(
                name='ProducerReport',
                fields={
                    'date_range': inline_serializer(
                        name='ProducerReportDateRange',
                        fields={
                            'start_date': drf_serializers.DateField(),
                            'end_date': drf_serializers.DateField(),
                        },
                    ),
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
                            'upload_date': drf_serializers.DateTimeField(help_text='When the movie was added to the platform'),
                            'release_date': drf_serializers.DateField(),
                            'views': drf_serializers.IntegerField(),
                            'total_watch_time_minutes': drf_serializers.FloatField(help_text='Lifetime sum of all viewer playback time in minutes'),
                            'avg_watch_duration_minutes': drf_serializers.FloatField(help_text='Lifetime average playback time per viewer in minutes'),
                            'completion_rate': drf_serializers.FloatField(help_text='Lifetime fraction of watchers who completed the movie (0–1)'),
                            'total_revenue': drf_serializers.IntegerField(help_text='Gross revenue in date range (RWF)'),
                            'platform_commission': drf_serializers.IntegerField(help_text='30% Ikigembe commission in date range (RWF)'),
                            'net_earnings': drf_serializers.IntegerField(help_text='Your 70% share in date range (RWF)'),
                            'purchase_count': drf_serializers.IntegerField(help_text='Completed purchases in date range'),
                            'payment_statuses': inline_serializer(
                                name='ProducerReportPaymentStatuses',
                                fields={
                                    'pending': drf_serializers.IntegerField(help_text='Payments not yet completed'),
                                    'failed': drf_serializers.IntegerField(help_text='Payments that failed'),
                                },
                            ),
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
        since, until = _parse_date_range(request)

        wallet = get_producer_wallet(request.user)
        movies = list(
            Movie.objects
            .filter(producer_profile=request.user)
            .order_by('-created_at')
        )
        movie_ids = [m.id for m in movies]

        # Aggregate payments separately to avoid cross-join inflation with WatchProgress.
        # Grouping by movie_id on a pre-filtered qs produces one row per movie.
        payment_agg = {
            row['movie_id']: row
            for row in Payment.objects.filter(movie_id__in=movie_ids).values('movie_id').annotate(
                total_revenue=Coalesce(
                    Sum('amount', filter=Q(status='Completed', created_at__gte=since, created_at__lte=until)), 0
                ),
                purchase_count=Count('id', filter=Q(status='Completed', created_at__gte=since, created_at__lte=until)),
                pending_count=Count('id', filter=Q(status='Pending')),
                failed_count=Count('id', filter=Q(status='Failed')),
            )
        }

        # Aggregate WatchProgress separately for the same reason.
        watch_agg = {
            row['movie_id']: row
            for row in WatchProgress.objects.filter(movie_id__in=movie_ids).values('movie_id').annotate(
                total_watch_seconds=Coalesce(Sum('progress_seconds'), 0),
                avg_watch_seconds=Avg('progress_seconds'),
                total_watches=Count('id'),
                completed_watches=Count('id', filter=Q(completed=True)),
            )
        }

        movies_data = []
        for movie in movies:
            p = payment_agg.get(movie.id, {})
            w = watch_agg.get(movie.id, {})
            total_watches = w.get('total_watches') or 0
            completed_watches = w.get('completed_watches') or 0
            completion_rate = round(completed_watches / total_watches, 4) if total_watches > 0 else 0.0
            avg_watch_seconds = w.get('avg_watch_seconds') or 0
            total_revenue = p.get('total_revenue') or 0
            net_earnings, platform_commission = producer_split(total_revenue)
            movies_data.append({
                'id': movie.id,
                'title': movie.title,
                'price': movie.price,
                'upload_date': movie.created_at,
                'release_date': movie.release_date,
                'views': movie.views,
                'total_watch_time_minutes': round((w.get('total_watch_seconds') or 0) / 60, 2),
                'avg_watch_duration_minutes': round(avg_watch_seconds / 60, 2),
                'completion_rate': completion_rate,
                'total_revenue': total_revenue,
                'platform_commission': platform_commission,
                'net_earnings': net_earnings,
                'purchase_count': p.get('purchase_count') or 0,
                'payment_statuses': {
                    'pending': p.get('pending_count') or 0,
                    'failed': p.get('failed_count') or 0,
                },
            })

        if request.GET.get('export') == 'csv':
            headers = [
                'Movie Title', 'Upload Date', 'Release Date', 'Price (RWF)', 'Views',
                'Total Watch Time (min)', 'Avg Watch Duration (min)', 'Completion Rate',
                'Total Revenue (RWF)', 'Platform Commission (RWF)', 'Net Earnings (RWF)',
                'Purchase Count', 'Pending Payments', 'Failed Payments',
            ]
            rows = [
                [
                    m['title'],
                    m['upload_date'].date() if m['upload_date'] else '',
                    m['release_date'],
                    m['price'],
                    m['views'],
                    m['total_watch_time_minutes'],
                    m['avg_watch_duration_minutes'],
                    m['completion_rate'],
                    m['total_revenue'],
                    m['platform_commission'],
                    m['net_earnings'],
                    m['purchase_count'],
                    m['payment_statuses']['pending'],
                    m['payment_statuses']['failed'],
                ]
                for m in movies_data
            ]
            return _csv_response('my-movies-report.csv', headers, rows)

        return Response({
            'date_range': {'start_date': since.date(), 'end_date': until.date()},
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
            'total buyers, watch engagement stats, and a paginated buyer list. '
            'Revenue is filterable by date range; watch stats are lifetime totals.'
        ),
        parameters=[
            OpenApiParameter('start_date', OpenApiTypes.DATE, OpenApiParameter.QUERY,
                             required=False, description='Filter revenue from this date (YYYY-MM-DD)'),
            OpenApiParameter('end_date', OpenApiTypes.DATE, OpenApiParameter.QUERY,
                             required=False, description='Filter revenue up to this date inclusive (YYYY-MM-DD)'),
            OpenApiParameter('page', OpenApiTypes.INT, OpenApiParameter.QUERY,
                             required=False, default=1, description='Page number for buyer list (20 per page)'),
        ],
        responses={
            200: inline_serializer(
                name='MovieAnalytics',
                fields={
                    'movie_id': drf_serializers.IntegerField(),
                    'title': drf_serializers.CharField(),
                    'views': drf_serializers.IntegerField(),
                    'total_buyers': drf_serializers.IntegerField(help_text='Completed purchases in date range'),
                    'gross_revenue': drf_serializers.IntegerField(help_text='Sum of completed payments in date range (RWF)'),
                    'platform_commission': drf_serializers.IntegerField(help_text='30% platform share (RWF)'),
                    'producer_earnings': drf_serializers.IntegerField(help_text='70% producer share (RWF)'),
                    'watch_stats': inline_serializer(
                        name='WatchStats',
                        fields={
                            'total_watchers': drf_serializers.IntegerField(help_text='Lifetime unique viewers who started watching'),
                            'completed_count': drf_serializers.IntegerField(help_text='Viewers who finished the movie'),
                            'completion_rate': drf_serializers.FloatField(help_text='Fraction of watchers who finished (0–1)'),
                            'avg_progress_percent': drf_serializers.FloatField(help_text='Average % of the movie watched (0–100)'),
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

        since, until = _parse_date_range(request, default_days=365)

        payments = Payment.objects.filter(
            movie=movie,
            status='Completed',
            created_at__gte=since,
            created_at__lte=until,
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

        # Lifetime watch stats — not date-filtered (engagement is cumulative)
        watch_qs = WatchProgress.objects.filter(movie=movie)
        total_watchers = watch_qs.count()
        completed_count = watch_qs.filter(completed=True).count()
        completion_rate = round(completed_count / total_watchers, 4) if total_watchers else 0.0
        avg_result = watch_qs.filter(duration_seconds__gt=0).aggregate(
            avg_pct=Avg(
                ExpressionWrapper(
                    F('progress_seconds') * 100.0 / F('duration_seconds'),
                    output_field=FloatField(),
                )
            )
        )
        avg_progress_percent = round(avg_result['avg_pct'] or 0.0, 1)

        return Response({
            'movie_id': movie.id,
            'title': movie.title,
            'views': movie.views,
            'total_buyers': total,
            'gross_revenue': gross,
            'platform_commission': commission,
            'producer_earnings': earnings,
            'watch_stats': {
                'total_watchers': total_watchers,
                'completed_count': completed_count,
                'completion_rate': completion_rate,
                'avg_progress_percent': avg_progress_percent,
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
            'Returns all-time KPIs plus earnings grouped by day (last 30 days), '
            'week (last 12 weeks), or month (last 12 months). '
            'KPIs include total gross revenue, net earnings, platform commission, '
            'best-performing movie, and average watch completion rate across all movies.'
        ),
        parameters=[
            OpenApiParameter('period', OpenApiTypes.STR, OpenApiParameter.QUERY,
                             required=False, enum=['daily', 'weekly', 'monthly'],
                             default='monthly', description='Grouping granularity for the trend section'),
            OpenApiParameter('start_date', OpenApiTypes.DATE, OpenApiParameter.QUERY,
                             required=False, description='Trend start date (YYYY-MM-DD). Overrides period default.'),
            OpenApiParameter('end_date', OpenApiTypes.DATE, OpenApiParameter.QUERY,
                             required=False, description='Trend end date inclusive (YYYY-MM-DD). Defaults to today.'),
            OpenApiParameter('export', OpenApiTypes.STR, OpenApiParameter.QUERY,
                             required=False, enum=['csv'], description='Set to "csv" to download as CSV'),
        ],
        responses={
            200: inline_serializer(
                name='EarningsReport',
                fields={
                    'kpis': inline_serializer(
                        name='EarningsKPIs',
                        fields={
                            'total_gross_revenue': drf_serializers.IntegerField(help_text='All-time gross revenue (RWF)'),
                            'total_net_earnings': drf_serializers.IntegerField(help_text='Your 70% all-time (RWF)'),
                            'total_platform_commission': drf_serializers.IntegerField(help_text='30% platform commission all-time (RWF)'),
                            'total_purchases': drf_serializers.IntegerField(help_text='All-time completed purchases'),
                            'total_movies': drf_serializers.IntegerField(),
                            'avg_revenue_per_movie': drf_serializers.IntegerField(help_text='RWF'),
                            'avg_completion_rate': drf_serializers.FloatField(help_text='Avg completion rate across all your movies (0–1)'),
                            'best_movie': inline_serializer(
                                name='BestMovie',
                                fields={
                                    'id': drf_serializers.IntegerField(allow_null=True),
                                    'title': drf_serializers.CharField(allow_null=True),
                                    'revenue': drf_serializers.IntegerField(allow_null=True),
                                },
                            ),
                        },
                    ),
                    'period': drf_serializers.CharField(help_text='daily | weekly | monthly'),
                    'trend': inline_serializer(
                        name='EarningsBucket',
                        fields={
                            'period_start': drf_serializers.DateTimeField(),
                            'gross_revenue': drf_serializers.IntegerField(help_text='RWF'),
                            'platform_commission': drf_serializers.IntegerField(help_text='30% (RWF)'),
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

        if period == 'daily':
            trunc_fn = TruncDay
            default_days = 30
        elif period == 'weekly':
            trunc_fn = TruncWeek
            default_days = 84  # 12 weeks
        else:
            period = 'monthly'
            trunc_fn = TruncMonth
            default_days = 365

        since, until = _parse_date_range(request, default_days=default_days)

        # ── Trend (period-grouped, date-range filtered) ─────────────────────
        rows = (
            Payment.objects.filter(
                movie__producer_profile=request.user,
                status='Completed',
                created_at__gte=since,
                created_at__lte=until,
            )
            .annotate(bucket=trunc_fn('created_at'))
            .values('bucket')
            .annotate(gross=Coalesce(Sum('amount'), 0), count=Count('id'))
            .order_by('bucket')
        )

        trend = []
        for row in rows:
            gross = row['gross']
            earnings, commission = producer_split(gross)
            trend.append({
                'period_start': row['bucket'],
                'gross_revenue': gross,
                'platform_commission': commission,
                'producer_earnings': earnings,
                'transactions': row['count'],
            })

        # ── All-time KPIs (not date-filtered — always lifetime totals) ───────
        all_payments = Payment.objects.filter(
            movie__producer_profile=request.user,
            status='Completed',
        )
        agg = all_payments.aggregate(gross=Coalesce(Sum('amount'), 0), purchases=Count('id'))
        total_gross = agg['gross']
        total_purchases = agg['purchases']
        total_net_earnings, total_platform_commission = producer_split(total_gross)

        total_movies = Movie.objects.filter(producer_profile=request.user).count()
        avg_revenue_per_movie = total_gross // total_movies if total_movies > 0 else 0

        best_row = (
            all_payments
            .values('movie_id', 'movie__title')
            .annotate(revenue=Sum('amount'))
            .order_by('-revenue')
            .first()
        )
        best_movie = (
            {'id': best_row['movie_id'], 'title': best_row['movie__title'], 'revenue': best_row['revenue']}
            if best_row else {'id': None, 'title': None, 'revenue': None}
        )

        watch_agg = WatchProgress.objects.filter(
            movie__producer_profile=request.user
        ).aggregate(
            total=Count('id'),
            completed=Count('id', filter=Q(completed=True)),
        )
        avg_completion_rate = (
            round(watch_agg['completed'] / watch_agg['total'], 4)
            if watch_agg['total'] else 0.0
        )

        kpis = {
            'total_gross_revenue': total_gross,
            'total_net_earnings': total_net_earnings,
            'total_platform_commission': total_platform_commission,
            'total_purchases': total_purchases,
            'total_movies': total_movies,
            'avg_revenue_per_movie': avg_revenue_per_movie,
            'avg_completion_rate': avg_completion_rate,
            'best_movie': best_movie,
        }

        if request.GET.get('export') == 'csv':
            kpi_headers = ['KPI', 'Value']
            kpi_rows = [
                ['Total Gross Revenue (RWF)', kpis['total_gross_revenue']],
                ['Total Net Earnings (RWF)', kpis['total_net_earnings']],
                ['Total Platform Commission (RWF)', kpis['total_platform_commission']],
                ['Total Purchases', kpis['total_purchases']],
                ['Total Movies', kpis['total_movies']],
                ['Avg Revenue Per Movie (RWF)', kpis['avg_revenue_per_movie']],
                ['Avg Completion Rate', kpis['avg_completion_rate']],
                ['Best Movie', f"{kpis['best_movie']['title']} ({kpis['best_movie']['revenue']} RWF)"
                 if kpis['best_movie']['title'] else 'N/A'],
            ]
            trend_headers = ['Period Start', 'Gross Revenue (RWF)',
                             'Platform Commission (RWF)', 'Net Earnings (RWF)', 'Transactions']
            trend_rows = [
                [
                    t['period_start'].date() if t['period_start'] else '',
                    t['gross_revenue'], t['platform_commission'],
                    t['producer_earnings'], t['transactions'],
                ]
                for t in trend
            ]
            from django.http import HttpResponse
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="earnings-report-{period}.csv"'
            import csv as _csv
            writer = _csv.writer(response)
            writer.writerows(kpi_rows)
            writer.writerow([])
            writer.writerow(trend_headers)
            writer.writerows(trend_rows)
            return response

        return Response({
            'kpis': kpis,
            'period': period,
            'trend': trend,
        })


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
