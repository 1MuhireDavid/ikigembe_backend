from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, inline_serializer
from rest_framework import serializers as drf_serializers
from django.db.models import Sum, Count, Q, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model

from apps.users.permissions import IsAdminRole
from apps.users.serializers import AdminCreateProducerSerializer
from apps.movies.models import Movie
from apps.payments.models import Payment, WithdrawalRequest

User = get_user_model()


class AdminBaseView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]


class AdminDashboardOverviewView(AdminBaseView):
    @extend_schema(
        tags=['Admin - Dashboard'],
        summary='Get platform overview',
        description='Returns top-level stats: total viewers, producers, movies, views, and financial summary.',
        responses={
            200: inline_serializer(
                name='DashboardOverview',
                fields={
                    'total_viewers': drf_serializers.IntegerField(),
                    'total_producers': drf_serializers.IntegerField(),
                    'total_movies': drf_serializers.IntegerField(),
                    'total_views': drf_serializers.IntegerField(),
                    'financials': drf_serializers.DictField(),
                }
            ),
            401: OpenApiResponse(description='Authentication required'),
            403: OpenApiResponse(description='Admin access required'),
        },
    )
    def get(self, request):
        total_viewers = User.objects.filter(role='Viewer').count()
        total_producers = User.objects.filter(role='Producer').count()
        total_movies = Movie.objects.count()
        total_views = Movie.objects.aggregate(total=Sum('views'))['total'] or 0
        
        total_revenue = Payment.objects.filter(status='Completed').aggregate(total=Sum('amount'))['total'] or 0
        producer_revenue = (total_revenue * 70) // 100
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
    @extend_schema(
        tags=['Admin - Viewers'],
        summary='List all viewers',
        description='Returns a list of all viewer accounts with their watch count and total payments made.',
        responses={
            200: inline_serializer(
                name='ViewerListItem',
                fields={
                    'id': drf_serializers.IntegerField(),
                    'name': drf_serializers.CharField(),
                    'email': drf_serializers.EmailField(),
                    'phone_number': drf_serializers.CharField(),
                    'movies_watched': drf_serializers.IntegerField(),
                    'payments_made': drf_serializers.IntegerField(),
                    'is_active': drf_serializers.BooleanField(),
                    'date_joined': drf_serializers.DateTimeField(),
                },
                many=True,
            ),
            401: OpenApiResponse(description='Authentication required'),
            403: OpenApiResponse(description='Admin access required'),
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
        tags=['Admin - Viewers'],
        summary="Get a viewer's payment history",
        description='Returns the full payment history for a specific viewer, ordered by most recent first.',
        responses={
            200: inline_serializer(
                name='ViewerPaymentItem',
                fields={
                    'id': drf_serializers.IntegerField(),
                    'movie_title': drf_serializers.CharField(),
                    'amount': drf_serializers.IntegerField(),
                    'status': drf_serializers.CharField(),
                    'created_at': drf_serializers.DateTimeField(),
                },
                many=True,
            ),
            401: OpenApiResponse(description='Authentication required'),
            403: OpenApiResponse(description='Admin access required'),
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


class AdminUserSuspendView(AdminBaseView):
    @extend_schema(
        tags=['Admin - Users'],
        summary='Suspend or unsuspend a user',
        description='Toggles `is_active` for a Viewer or Producer. Cannot be used on Admin accounts.',
        responses={
            200: inline_serializer(
                name='SuspendUserResponse',
                fields={
                    'message': drf_serializers.CharField(),
                    'is_active': drf_serializers.BooleanField(),
                },
            ),
            400: OpenApiResponse(description='Cannot suspend another Admin'),
            401: OpenApiResponse(description='Authentication required'),
            403: OpenApiResponse(description='Admin access required'),
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
        tags=['Admin - Users'],
        summary='Delete a user account',
        description='Permanently deletes a Viewer or Producer account. Cannot be used on Admin accounts.',
        responses={
            204: OpenApiResponse(description='User deleted successfully'),
            400: OpenApiResponse(description='Cannot delete an Admin'),
            401: OpenApiResponse(description='Authentication required'),
            403: OpenApiResponse(description='Admin access required'),
            404: OpenApiResponse(description='User not found'),
        },
    )
    def delete(self, request, user_id):
        user = get_object_or_404(User, id=user_id)
        if user.role == 'Admin':
            return Response({'error': 'Cannot delete an Admin'}, status=status.HTTP_400_BAD_REQUEST)
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminProducersListView(AdminBaseView):
    @extend_schema(
        tags=['Admin - Producers'],
        summary='List all producers',
        description='Returns all producer accounts with earnings, balance, movies uploaded, and pending withdrawal stats.',
        responses={
            200: inline_serializer(
                name='ProducerListItem',
                fields={
                    'id': drf_serializers.IntegerField(),
                    'name': drf_serializers.CharField(),
                    'email': drf_serializers.EmailField(),
                    'phone_number': drf_serializers.CharField(),
                    'movies_uploaded': drf_serializers.IntegerField(),
                    'total_earnings': drf_serializers.IntegerField(),
                    'balance': drf_serializers.IntegerField(),
                    'pending_withdrawals': drf_serializers.IntegerField(),
                    'is_active': drf_serializers.BooleanField(),
                    'date_joined': drf_serializers.DateTimeField(),
                },
                many=True,
            ),
            401: OpenApiResponse(description='Authentication required'),
            403: OpenApiResponse(description='Admin access required'),
        },
    )
    def get(self, request):
        payments_sum = Payment.objects.filter(
            movie__producer_profile=OuterRef('pk'),
            status='Completed'
        ).values('movie__producer_profile').annotate(
            total=Sum('amount')
        ).values('total')

        withdrawn_sum = WithdrawalRequest.objects.filter(
            producer=OuterRef('pk'),
            status='Approved'
        ).values('producer').annotate(
            total=Sum('amount')
        ).values('total')

        pending_sum = WithdrawalRequest.objects.filter(
            producer=OuterRef('pk'),
            status='Pending'
        ).values('producer').annotate(
            total=Sum('amount')
        ).values('total')

        producers = User.objects.filter(role='Producer').annotate(
            movies_uploaded_count=Count('uploaded_movies', distinct=True),
            db_total_revenue=Coalesce(Subquery(payments_sum), 0),
            db_total_withdrawn=Coalesce(Subquery(withdrawn_sum), 0),
            db_pending_withdrawals=Coalesce(Subquery(pending_sum), 0),
        )
        data = []
        for p in producers:
            total_revenue = getattr(p, 'db_total_revenue', 0)
            earnings = (total_revenue * 70) // 100
            
            total_withdrawn = getattr(p, 'db_total_withdrawn', 0)
            pending_withdrawals = getattr(p, 'db_pending_withdrawals', 0)
            
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
    @extend_schema(
        tags=['Admin - Producers'],
        summary='Approve a producer account',
        description='Sets `is_active=True` for a producer. Returns a message if already active.',
        responses={
            200: inline_serializer(
                name='ProducerApproveResponse',
                fields={'message': drf_serializers.CharField()},
            ),
            401: OpenApiResponse(description='Authentication required'),
            403: OpenApiResponse(description='Admin access required'),
            404: OpenApiResponse(description='Producer not found'),
        },
    )
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
    @extend_schema(
        tags=['Admin - Producers'],
        summary='Suspend a producer account',
        description='Sets `is_active=False` for a producer, preventing them from logging in.',
        responses={
            200: inline_serializer(
                name='ProducerSuspendResponse',
                fields={'message': drf_serializers.CharField()},
            ),
            401: OpenApiResponse(description='Authentication required'),
            403: OpenApiResponse(description='Admin access required'),
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
        tags=['Admin - Producers'],
        summary='Create a new producer account',
        description='Creates a new user account with the Producer role. At least one of `email` or `phone_number` is required.',
        request=AdminCreateProducerSerializer,
        responses={
            201: inline_serializer(
                name='CreateProducerResponse',
                fields={
                    'message': drf_serializers.CharField(),
                    'user': inline_serializer(
                        name='CreatedProducerUser',
                        fields={
                            'id': drf_serializers.IntegerField(),
                            'email': drf_serializers.EmailField(),
                            'phone_number': drf_serializers.CharField(),
                            'first_name': drf_serializers.CharField(),
                            'last_name': drf_serializers.CharField(),
                            'role': drf_serializers.CharField(),
                        },
                    ),
                },
            ),
            400: OpenApiResponse(description='Validation error'),
            401: OpenApiResponse(description='Authentication required'),
            403: OpenApiResponse(description='Admin access required'),
        },
    )
    def post(self, request):
        serializer = AdminCreateProducerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        
        # We can re-use the detail representation if needed, 
        # but for simplicity return the created data
        return Response({
            'message': 'Producer created successfully',
            'user': {
                'id': user.id,
                'email': user.email,
                'phone_number': user.phone_number,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'role': user.role
            }
        }, status=status.HTTP_201_CREATED)
