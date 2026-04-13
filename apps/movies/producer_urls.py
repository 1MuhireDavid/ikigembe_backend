from django.urls import path
from .producer_views import (
    ProducerMyMoviesView,
    ProducerMovieDetailView,
    ProducerWalletView,
    ProducerWithdrawalsView,
    ProducerMovieAnalyticsView,
    ProducerEarningsReportView,
    ProducerTransactionHistoryView,
    ProducerReportView,
)

urlpatterns = [
    path('movies/', ProducerMyMoviesView.as_view(), name='producer-my-movies'),
    path('movies/<int:id>/', ProducerMovieDetailView.as_view(), name='producer-movie-detail'),
    path('movies/<int:id>/analytics/', ProducerMovieAnalyticsView.as_view(), name='producer-movie-analytics'),
    path('wallet/', ProducerWalletView.as_view(), name='producer-wallet'),
    path('withdrawals/', ProducerWithdrawalsView.as_view(), name='producer-withdrawals'),
    path('earnings/report/', ProducerEarningsReportView.as_view(), name='producer-earnings-report'),
    path('transactions/', ProducerTransactionHistoryView.as_view(), name='producer-transactions'),
    path('report/', ProducerReportView.as_view(), name='producer-report'),
]
