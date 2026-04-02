from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status, serializers as drf_serializers
from drf_spectacular.utils import extend_schema, inline_serializer, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from apps.users.permissions import IsProducerRole
from apps.movies.models import Movie
from apps.movies.serializers import ProducerMovieListSerializer, ProducerMovieDetailSerializer
from apps.payments.models import Payment, WithdrawalRequest
from apps.payments.serializers import WithdrawalRequestSerializer, get_producer_wallet


def _safe_page(request):
    """Return a valid page number from ?page=, defaulting to 1 for any invalid input."""
    try:
        return max(1, int(request.GET.get('page', 1)))
    except (TypeError, ValueError):
        return 1

_TAG = 'Producer Dashboard'


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
                    'total_earnings': drf_serializers.IntegerField(help_text='70% of all completed revenue from your movies (RWF)'),
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
                status__in=['Pending', 'Approved', 'Completed'],
            ).aggregate(total=Coalesce(Sum('amount'), 0))['total']

            raw_revenue = Payment.objects.filter(
                movie__producer_profile=request.user,
                status='Completed',
            ).aggregate(total=Coalesce(Sum('amount'), 0))['total']

            balance = (raw_revenue * 70) // 100 - locked

            if amount > balance:
                return Response(
                    {'error': f"Amount exceeds available balance of {balance} RWF."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            serializer.save(producer=request.user, status='Pending')

        return Response(serializer.data, status=status.HTTP_201_CREATED)
