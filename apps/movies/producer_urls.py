from django.urls import path
from .producer_views import (
    ProducerMyMoviesView,
    ProducerMovieDetailView,
    ProducerWalletView,
    ProducerWithdrawalsView,
    ProducerReportView,
    ProducerRevenueTrendView,
    ProducerMoviePurchasesView,
)

urlpatterns = [
    path('movies/', ProducerMyMoviesView.as_view(), name='producer-my-movies'),
    path('movies/<int:id>/', ProducerMovieDetailView.as_view(), name='producer-movie-detail'),
    path('wallet/', ProducerWalletView.as_view(), name='producer-wallet'),
    path('withdrawals/', ProducerWithdrawalsView.as_view(), name='producer-withdrawals'),
    path('report/', ProducerReportView.as_view(), name='producer-report'),
    path('revenue-trend/', ProducerRevenueTrendView.as_view(), name='producer-revenue-trend'),
    path('movies/<int:id>/purchases/', ProducerMoviePurchasesView.as_view(), name='producer-movie-purchases'),
]
