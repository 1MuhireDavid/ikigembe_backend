import secrets

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from django.db.models import Sum, Count, Q, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.users.permissions import IsAdminRole
from apps.movies.models import Movie
from apps.payments.models import Payment, WithdrawalRequest
from apps.payments.serializers import AdminWithdrawalRequestSerializer, get_producer_wallet

User = get_user_model()


class AdminBaseView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]


class AdminDashboardOverviewView(AdminBaseView):
    @extend_schema(summary="Get top-level summary of platform activity")
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

class AdminTransactionHistoryView(AdminBaseView):
    @extend_schema(summary="Get all platform transactions (payments, withdrawals, pending withdrawals)")
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
            'created_at': p.created_at
        } for p in payments]
        
        withdrawals_data = [{
            'id': w.id,
            'producer': w.producer.full_name,
            'amount': w.amount,
            'status': w.status,
            'created_at': w.created_at,
            'processed_at': w.processed_at
        } for w in withdrawals]
        
        pending_data = [{
            'id': w.id,
            'producer': w.producer.full_name,
            'amount': w.amount,
            'status': w.status,
            'created_at': w.created_at
        } for w in pending_withdrawals]
        
        return Response({
            'payments': payments_data,
            'withdrawals': withdrawals_data,
            'pending_withdrawals': pending_data
        })


class AdminViewersListView(AdminBaseView):
    @extend_schema(summary="List all viewers with their stats (movies watched, payments made)")
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
    @extend_schema(summary="View a specific viewer's payment history")
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


class AdminUserSuspendView(AdminBaseView):
    @extend_schema(summary="Suspend or unsuspend a user account (Viewer/Producer)")
    def post(self, request, user_id):
        user = get_object_or_404(User, id=user_id)
        if user.role == 'Admin':
            return Response({'error': 'Cannot suspend another Admin'}, status=status.HTTP_400_BAD_REQUEST)
            
        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])
        state = "activated" if user.is_active else "suspended"
        return Response({'message': f'User {state} successfully', 'is_active': user.is_active})


class AdminUserDeleteView(AdminBaseView):
    @extend_schema(summary="Delete a user account")
    def delete(self, request, user_id):
        user = get_object_or_404(User, id=user_id)
        if user.role == 'Admin':
            return Response({'error': 'Cannot delete an Admin'}, status=status.HTTP_400_BAD_REQUEST)
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminProducersListView(AdminBaseView):
    @extend_schema(summary="List all producers with their stats (earnings, movies, withdrawals)")
    def get(self, request):
        producers = User.objects.filter(role='Producer').annotate(
            movies_uploaded_count=Count('uploaded_movies', distinct=True),
        )
        data = []
        for p in producers:
            wallet = get_producer_wallet(p)
            data.append({
                'id': p.id,
                'name': p.full_name,
                'email': p.email,
                'phone_number': p.phone_number,
                'movies_uploaded': p.movies_uploaded_count,
                'total_earnings': wallet['total_earnings'],
                'balance': wallet['wallet_balance'],
                'pending_withdrawals': wallet['pending_withdrawals'],
                'total_withdrawn': wallet['total_withdrawn'],
                'is_active': p.is_active,
                'date_joined': p.date_joined,
            })
        return Response(data)


class AdminProducerApproveView(AdminBaseView):
    @extend_schema(summary="Approve a producer account (set is_active=True)")
    def post(self, request, user_id):
        producer = get_object_or_404(User, id=user_id, role='Producer')
        
        # In this implementation, 'approval' sets them to active 
        # (they might be created as inactive by default in the future)
        if producer.is_active:
            return Response({'message': 'Producer is already approved (active)'}, status=status.HTTP_200_OK)
            
        producer.is_active = True
        producer.save(update_fields=['is_active'])
        return Response({'message': 'Producer approved successfully'})


class AdminProducerSuspendView(AdminBaseView):
    @extend_schema(summary="Suspend a producer account (set is_active=False)")
    def post(self, request, user_id):
        producer = get_object_or_404(User, id=user_id, role='Producer')
        producer.is_active = False
        producer.save(update_fields=['is_active'])
        return Response({'message': 'Producer suspended successfully'})


class AdminCreateProducerView(AdminBaseView):
    @extend_schema(summary="Create a new producer account with an auto-generated password")
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
        summary="List all producer withdrawal requests",
        description="Optionally filter by status: ?status=Pending|Approved|Completed|Rejected",
    )
    def get(self, request):
        qs = WithdrawalRequest.objects.select_related('producer').order_by('-created_at')
        status_filter = request.GET.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        page = int(request.GET.get('page', 1))
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
    @extend_schema(summary="Approve a withdrawal request (Pending → Approved)")
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

        return Response({
            'message': 'Withdrawal approved successfully.',
            'id': withdrawal.id,
            'status': withdrawal.status,
            'processed_at': withdrawal.processed_at,
        })


class AdminWithdrawalCompleteView(AdminBaseView):
    @extend_schema(
        summary="Mark a withdrawal as completed (Approved → Completed)",
        description="Finance confirms the bank/MoMo transfer. Completed records are immutable.",
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

        withdrawal.status = 'Completed'
        withdrawal.save(update_fields=['status'])

        return Response({
            'message': 'Withdrawal marked as completed.',
            'id': withdrawal.id,
            'status': withdrawal.status,
        })


class AdminWithdrawalRejectView(AdminBaseView):
    @extend_schema(
        summary="Reject a withdrawal request (Pending/Approved → Rejected)",
        description="Rejected amounts are automatically freed back to the producer's wallet balance.",
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

        return Response({
            'message': 'Withdrawal rejected.',
            'id': withdrawal.id,
            'status': withdrawal.status,
        })
