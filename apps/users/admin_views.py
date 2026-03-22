from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from django.db.models import Sum, Count, Q
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model

from apps.users.permissions import IsAdminRole
from apps.movies.models import Movie
from apps.payments.models import Payment, WithdrawalRequest

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
        
        total_revenue = Payment.objects.filter(status='Completed').aggregate(total=Sum('amount'))['total'] or 0
        producer_revenue = int(total_revenue * 0.7)
        ikigembe_commission = total_revenue - producer_revenue
        
        return Response({
            'total_viewers': total_viewers,
            'total_producers': total_producers,
            'total_movies': total_movies,
            'total_views': total_views,
            'financials': {
                'total_revenue': total_revenue,
                'producer_revenue': producer_revenue,
                'ikigembe_commission': ikigembe_commission
            }
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
            total_revenue = Payment.objects.filter(
                movie__producer_profile=p, 
                status='Completed'
            ).aggregate(total=Sum('amount'))['total'] or 0
            
            earnings = int(total_revenue * 0.7)
            
            total_withdrawn = WithdrawalRequest.objects.filter(
                producer=p,
                status='Approved'
            ).aggregate(total=Sum('amount'))['total'] or 0
            
            pending_withdrawals = WithdrawalRequest.objects.filter(
                producer=p,
                status='Pending'
            ).aggregate(total=Sum('amount'))['total'] or 0
            
            data.append({
                'id': p.id,
                'name': p.full_name,
                'email': p.email,
                'phone_number': p.phone_number,
                'movies_uploaded': p.movies_uploaded_count,
                'total_earnings': earnings,
                'balance': earnings - total_withdrawn,
                'pending_withdrawals': pending_withdrawals,
                'is_active': p.is_active,
                'date_joined': p.date_joined
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
