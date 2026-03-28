from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from drf_spectacular.utils import extend_schema

from apps.users.permissions import IsProducerRole
from apps.movies.models import Movie
from apps.movies.serializers import ProducerMovieListSerializer
from apps.payments.models import WithdrawalRequest
from apps.payments.serializers import WithdrawalRequestSerializer, get_producer_wallet


class ProducerBaseView(APIView):
    permission_classes = [IsAuthenticated, IsProducerRole]


class ProducerMyMoviesView(ProducerBaseView):
    @extend_schema(
        tags=["Producer Dashboard"],
        summary="List my movies",
        description=(
            "Returns all movies belonging to the authenticated producer, ordered by most recently added. "
            "Read-only — uploading, editing, and deleting movies is handled by the Admin."
        ),
    )
    def get(self, request):
        movies = Movie.objects.filter(
            producer_profile=request.user
        ).order_by('-created_at')

        page = int(request.GET.get('page', 1))
        page_size = 20
        start = (page - 1) * page_size
        total = movies.count()

        return Response({
            'page': page,
            'results': ProducerMovieListSerializer(movies[start:start + page_size], many=True).data,
            'total_results': total,
            'total_pages': (total + page_size - 1) // page_size,
        })


class ProducerWalletView(ProducerBaseView):
    @extend_schema(
        tags=["Producer Dashboard"],
        summary="Get my wallet balance",
        description=(
            "Returns the producer's earnings breakdown in real-time. "
            "All figures are in RWF and read-only — they cannot be manually modified. "
            "wallet_balance is what is currently available to withdraw."
        ),
    )
    def get(self, request):
        return Response(get_producer_wallet(request.user))


class ProducerWithdrawalsView(ProducerBaseView):
    @extend_schema(
        tags=["Producer Dashboard"],
        summary="List my withdrawal requests",
    )
    def get(self, request):
        qs = WithdrawalRequest.objects.filter(producer=request.user)
        page = int(request.GET.get('page', 1))
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
        tags=["Producer Dashboard"],
        summary="Request a payout",
        description=(
            "Submit a withdrawal request. Amount must not exceed your current wallet_balance. "
            "Provide either Bank details (bank_name, account_number, account_holder_name) "
            "or MoMo details (momo_number, momo_provider) depending on payment_method."
        ),
    )
    def post(self, request):
        serializer = WithdrawalRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        amount = serializer.validated_data['amount']
        wallet = get_producer_wallet(request.user)

        if amount > wallet['wallet_balance']:
            return Response(
                {'error': f"Amount exceeds available balance of {wallet['wallet_balance']} RWF."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer.save(producer=request.user, status='Pending')
        return Response(serializer.data, status=status.HTTP_201_CREATED)
