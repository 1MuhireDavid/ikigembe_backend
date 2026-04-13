from django.urls import path
from .admin_views import (
    AdminDashboardOverviewView,
    AdminTransactionHistoryView,
    AdminViewersListView,
    AdminViewerDetailView,
    AdminViewerPaymentsView,
    AdminUserSuspendView,
    AdminUserDeleteView,
    AdminProducersListView,
    AdminProducerApproveView,
    AdminProducerSuspendView,
    AdminProducerDetailView,
    AdminProducerMoviesView,
    AdminProducerReportView,
    AdminCreateProducerView,
    AdminWithdrawalsListView,
    AdminWithdrawalApproveView,
    AdminWithdrawalCompleteView,
    AdminWithdrawalRejectView,
    AdminAuditLogView,
    AdminUserResetPasswordView,
    AdminRevenueTrendView,
    AdminTopMoviesView,
    AdminUserGrowthView,
    AdminWithdrawalSummaryView,
    AdminProducerMoviePurchasesView,
    AdminPayingUsersReportView,
    AdminGenreRevenueView,
    AdminHLSHealthView,
    AdminWithdrawalPerformanceView,
    AdminPaymentLookupView,
    AdminPaymentResolveView,
)

urlpatterns = [
    path('overview/', AdminDashboardOverviewView.as_view(), name='admin-dashboard-overview'),
    path('transactions/', AdminTransactionHistoryView.as_view(), name='admin-dashboard-transactions'),
    
    # Viewers
    path('viewers/', AdminViewersListView.as_view(), name='admin-viewers-list'),
    path('viewers/<int:user_id>/', AdminViewerDetailView.as_view(), name='admin-viewer-detail'),
    path('viewers/<int:user_id>/payments/', AdminViewerPaymentsView.as_view(), name='admin-viewer-payments'),
    
    # Generic User Actions (suspend works for both Viewer and Producer)
    path('users/<int:user_id>/suspend/', AdminUserSuspendView.as_view(), name='admin-user-suspend'),
    path('users/<int:user_id>/', AdminUserDeleteView.as_view(), name='admin-user-delete'),
    
    # Producers
    path('producers/', AdminProducersListView.as_view(), name='admin-producers-list'),
    path('producers/create/', AdminCreateProducerView.as_view(), name='admin-producer-create'),
    path('producers/<int:user_id>/', AdminProducerDetailView.as_view(), name='admin-producer-detail'),
    path('producers/<int:user_id>/movies/', AdminProducerMoviesView.as_view(), name='admin-producer-movies'),
    path('producers/<int:user_id>/approve/', AdminProducerApproveView.as_view(), name='admin-producer-approve'),
    path('producers/<int:user_id>/suspend/', AdminProducerSuspendView.as_view(), name='admin-producer-suspend'),
    path('producers/<int:user_id>/report/', AdminProducerReportView.as_view(), name='admin-producer-report'),
    path('producers/<int:user_id>/movies/<int:movie_id>/purchases/', AdminProducerMoviePurchasesView.as_view(), name='admin-producer-movie-purchases'),

    # Analytics Reports
    path('reports/revenue-trend/', AdminRevenueTrendView.as_view(), name='admin-revenue-trend'),
    path('reports/top-movies/', AdminTopMoviesView.as_view(), name='admin-top-movies'),
    path('reports/user-growth/', AdminUserGrowthView.as_view(), name='admin-user-growth'),
    path('reports/withdrawal-summary/', AdminWithdrawalSummaryView.as_view(), name='admin-withdrawal-summary'),
    path('reports/paying-users/', AdminPayingUsersReportView.as_view(), name='admin-paying-users-report'),
    path('reports/genre-revenue/', AdminGenreRevenueView.as_view(), name='admin-genre-revenue'),
    path('reports/hls-health/', AdminHLSHealthView.as_view(), name='admin-hls-health'),
    path('reports/withdrawal-performance/', AdminWithdrawalPerformanceView.as_view(), name='admin-withdrawal-performance'),

    # Payment Dispute Resolution
    path('payments/lookup/', AdminPaymentLookupView.as_view(), name='admin-payment-lookup'),
    path('payments/<int:payment_id>/resolve/', AdminPaymentResolveView.as_view(), name='admin-payment-resolve'),

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
