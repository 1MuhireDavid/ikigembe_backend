from django.urls import path
from .admin_views import (
    AdminDashboardOverviewView,
    AdminViewersListView,
    AdminViewerPaymentsView,
    AdminUserSuspendView,
    AdminUserDeleteView,
    AdminProducersListView,
    AdminProducerApproveView,
    AdminProducerSuspendView,
)

urlpatterns = [
    path('overview/', AdminDashboardOverviewView.as_view(), name='admin-dashboard-overview'),
    
    # Viewers
    path('viewers/', AdminViewersListView.as_view(), name='admin-viewers-list'),
    path('viewers/<int:user_id>/payments/', AdminViewerPaymentsView.as_view(), name='admin-viewer-payments'),
    
    # Generic User Actions (suspend works for both Viewer and Producer)
    path('users/<int:user_id>/suspend/', AdminUserSuspendView.as_view(), name='admin-user-suspend'),
    path('users/<int:user_id>/', AdminUserDeleteView.as_view(), name='admin-user-delete'),
    
    # Producers
    path('producers/', AdminProducersListView.as_view(), name='admin-producers-list'),
    path('producers/<int:user_id>/approve/', AdminProducerApproveView.as_view(), name='admin-producer-approve'),
    path('producers/<int:user_id>/suspend/', AdminProducerSuspendView.as_view(), name='admin-producer-suspend'),
]
