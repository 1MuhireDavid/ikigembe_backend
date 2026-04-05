from django.urls import path
from .admin_views import (
    AdminDashboardOverviewView,
    AdminTransactionHistoryView,
    AdminViewersListView,
    AdminViewerPaymentsView,
    AdminUserSuspendView,
    AdminUserDeleteView,
    AdminProducersListView,
    AdminProducerApproveView,
    AdminProducerSuspendView,
    AdminCreateProducerView,
    AdminWithdrawalsListView,
    AdminWithdrawalApproveView,
    AdminWithdrawalCompleteView,
    AdminWithdrawalRejectView,
    AdminAuditLogView,
    AdminUserResetPasswordView,
)

urlpatterns = [
    path('overview/', AdminDashboardOverviewView.as_view(), name='admin-dashboard-overview'),
    path('transactions/', AdminTransactionHistoryView.as_view(), name='admin-dashboard-transactions'),
    
    # Viewers
    path('viewers/', AdminViewersListView.as_view(), name='admin-viewers-list'),
    path('viewers/<int:user_id>/payments/', AdminViewerPaymentsView.as_view(), name='admin-viewer-payments'),
    
    # Generic User Actions (suspend works for both Viewer and Producer)
    path('users/<int:user_id>/suspend/', AdminUserSuspendView.as_view(), name='admin-user-suspend'),
    path('users/<int:user_id>/', AdminUserDeleteView.as_view(), name='admin-user-delete'),
    
    # Producers
    path('producers/', AdminProducersListView.as_view(), name='admin-producers-list'),
    path('producers/create/', AdminCreateProducerView.as_view(), name='admin-producer-create'),
    path('producers/<int:user_id>/approve/', AdminProducerApproveView.as_view(), name='admin-producer-approve'),
    path('producers/<int:user_id>/suspend/', AdminProducerSuspendView.as_view(), name='admin-producer-suspend'),

    # Withdrawal Requests
    path('withdrawals/', AdminWithdrawalsListView.as_view(), name='admin-withdrawals-list'),
    path('withdrawals/<int:withdrawal_id>/approve/', AdminWithdrawalApproveView.as_view(), name='admin-withdrawal-approve'),
    path('withdrawals/<int:withdrawal_id>/complete/', AdminWithdrawalCompleteView.as_view(), name='admin-withdrawal-complete'),
    path('withdrawals/<int:withdrawal_id>/reject/', AdminWithdrawalRejectView.as_view(), name='admin-withdrawal-reject'),

    # Audit Log
    path('audit-logs/', AdminAuditLogView.as_view(), name='admin-audit-logs'),

    # Password reset (for phone-only accounts)
    path('users/<int:user_id>/reset-password/', AdminUserResetPasswordView.as_view(), name='admin-user-reset-password'),
]
